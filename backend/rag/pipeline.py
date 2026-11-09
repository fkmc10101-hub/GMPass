"""문서 적재(ingest)와 질의응답(answer)을 묶은 RAG 파이프라인."""

from __future__ import annotations

from dataclasses import dataclass, field

from .chunker import Chunk, chunk_pages, chunk_records
from .embeddings import Embedder
from .generator import DryRunGenerator, OpenAIGenerator
from .countries import JURISDICTIONS
from .glossary import expand_query
from .intent import detect
from .keyword import BM25Index, rrf
from .loaders import load_file, load_records
from .tracing import Trace
from .vectorstore import SearchHit, VectorStore
from .verifier import Verdict, verify


@dataclass
class RagSettings:
    top_k: int = 5
    chunk_max_chars: int = 1000
    chunk_overlap_chars: int = 150
    min_retrieval_score: float = 0.35
    self_consistency_n: int = 3
    self_consistency_threshold: float = 0.75
    query_expansion: bool = True  # 한국어 GMP 용어 → 영어·일본어 대응어 덧붙여 검색 (rag/glossary.py)
    hybrid_search: bool = True    # 의미 검색 + 키워드(BM25) 검색을 순위 기준으로 합침 (rag/keyword.py)


@dataclass
class DocumentMeta:
    document_id: int
    country: str
    title: str
    doc_code: str = ""
    version: str = ""
    effective_date: str = ""
    language: str = ""
    source_url: str = ""


@dataclass
class CountryAnswer:
    country: str  # 비교 모드가 아니면 "ALL"
    answer: str
    hits: list[SearchHit]
    cited_refs: list[int]
    verdict: Verdict
    model: str


@dataclass
class AnswerResult:
    mode: str
    answers: list[CountryAnswer]
    trace: Trace
    model: str
    warnings: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)  # 실제로 답한 나라 (질문에서 나라를 읽어 바뀔 수 있음)


class RagPipeline:
    def __init__(self, store: VectorStore, embedder: Embedder, generator, settings: RagSettings):
        self.store = store
        self.embedder = embedder
        self.generator = generator
        self.settings = settings

    @property
    def is_dry_run(self) -> bool:
        return isinstance(self.generator, DryRunGenerator)

    # ---------- 적재 ----------
    def ingest(self, path: str, meta: DocumentMeta) -> list[Chunk]:
        if str(path).lower().endswith(".jsonl"):
            # 조항 단위로 미리 정리된 레코드 (scripts/prepare_sources.py)
            chunks = chunk_records(load_records(path), self.settings.chunk_max_chars, self.settings.chunk_overlap_chars)
        else:
            pages = load_file(path)
            chunks = chunk_pages(pages, self.settings.chunk_max_chars, self.settings.chunk_overlap_chars)
        if not chunks:
            raise ValueError("문서에서 청크를 만들지 못했습니다.")
        self.store.delete_document(meta.document_id)  # 재색인 시 기존 벡터 제거
        self._bm25 = None  # 문서가 바뀌었으므로 키워드 색인을 다시 만든다
        vectors = self.embedder.embed_documents([c.text for c in chunks])
        self.store.add(
            ids=[VectorStore.vector_id(meta.document_id, c.index) for c in chunks],
            embeddings=vectors,
            texts=[c.text for c in chunks],
            metadatas=[
                {
                    "document_id": meta.document_id,
                    "chunk_index": c.index,
                    "country": meta.country,
                    "title": meta.title,
                    "doc_code": meta.doc_code,
                    "version": meta.version,
                    "effective_date": meta.effective_date,
                    "language": meta.language,
                    "source_url": meta.source_url,
                    "section": c.section,
                    "page": c.page if c.page is not None else -1,
                    "record_id": c.record_id,
                    "topics": c.topics,
                }
                for c in chunks
            ],
        )
        return chunks

    # ---------- 검색 ----------
    def search(self, question: str, countries: list[str], top_k: int | None = None) -> list[SearchHit]:
        k = top_k or self.settings.top_k
        text = expand_query(question) if self.settings.query_expansion else question
        q = self.embedder.embed_query(text)
        if not self.settings.hybrid_search:
            return self.store.search(q, countries, k)

        # 1) 의미 검색 후보와 2) 키워드 검색 후보를 넉넉히 뽑아 3) 순위 기준(RRF)으로 합친다
        pool = max(20, k * 4)
        dense = self.store.search(q, countries, pool)
        bm25 = self._keyword_index()
        sparse = [vid for vid, _ in bm25.search(text, countries, pool)] if bm25 else []
        fused = rrf([[h.vector_id for h in dense], sparse])[:k]
        known = {h.vector_id: h for h in dense}
        missing = [vid for vid in fused if vid not in known]
        for h in self.store.get_with_scores(missing, q):
            known[h.vector_id] = h
        return [known[vid] for vid in fused if vid in known]

    def _keyword_index(self) -> BM25Index | None:
        n = self.store.count()
        if n == 0:
            return None
        if getattr(self, "_bm25", None) is None or self._bm25_count != n:
            self._bm25 = BM25Index(*self.store.all_documents())
            self._bm25_count = n
        return self._bm25

    # ---------- 질의응답 ----------
    def _answer_one(self, label: str, question: str, countries: list[str], trace: Trace,
                    search_query: str | None = None) -> CountryAnswer:
        with trace.span(f"retrieve:{label}", countries=countries) as s:
            hits = self.search(search_query or question, countries)
            s["hits"] = len(hits)
            s["top_score"] = max((h.score for h in hits), default=0.0)
        with trace.span(f"generate:{label}"):
            n = 1 if self.is_dry_run else self.settings.self_consistency_n
            gen = self.generator.generate(question, hits, n_samples=n)
        with trace.span(f"verify:{label}"):
            verdict = verify(
                gen, hits, self.embedder,
                self.settings.min_retrieval_score, self.settings.self_consistency_threshold,
            )
        return CountryAnswer(label, gen.answer, hits, gen.source_refs, verdict, gen.model)

    def _compare_summary(self, question: str, per_country: list[CountryAnswer], trace: Trace) -> CountryAnswer:
        """나라별 검색 결과를 모아 한 번에 공통점·차이점을 정리한다 (나라당 상위 3개 근거)."""
        hits = [h for a in per_country for h in a.hits[:3]]
        with trace.span("generate:DIFF"):
            gen = self.generator.compare(question, hits)
        with trace.span("verify:DIFF"):
            verdict = verify(gen, hits, self.embedder, self.settings.min_retrieval_score,
                             self.settings.self_consistency_threshold)
        return CountryAnswer("DIFF", gen.answer, hits, gen.source_refs, verdict, gen.model)

    def answer(self, question: str, countries: list[str], mode: str = "single") -> AnswerResult:
        intent = detect(question)
        mentioned = [c for c in intent.countries if c in JURISDICTIONS]
        search_query = None
        # '한국과 미국의 차이'처럼 나라 간 비교를 묻는 질문은 통합 답변이어도 비교 모드로 처리한다
        if intent.is_compare:
            if len(mentioned) >= 2:
                countries = mentioned
            if len(countries) >= 2:
                mode = "compare"
        # '미국 cGMP에서 ~'처럼 한 나라만 콕 집어 물으면 그 나라 문서에서만 찾는다
        # (한국어 질문이라 한국 문서가 검색 상위를 차지하는 문제 방지, 2026-11-09)
        elif len(mentioned) == 1 and mode == "single":
            countries = mentioned
            search_query = intent.topic
        trace = Trace("gmpass.ask", {"question": question, "countries": countries, "mode": mode,
                                     "topic": intent.topic})
        answers: list[CountryAnswer] = []
        if mode == "compare":
            # 국가별로 따로 검색해야 한 나라 문서가 검색 상위를 독차지하지 않는다.
            # 검색어에는 '한국/미국/차이' 같은 말을 빼고 주제만 쓴다.
            topic = intent.topic or question
            for c in countries:
                name = JURISDICTIONS[c].name_ko
                answers.append(self._answer_one(c, f"{name} 기준으로: {topic}", [c], trace, search_query=topic))
            answers.insert(0, self._compare_summary(question, answers, trace))
        else:
            answers.append(self._answer_one("ALL", question, countries, trace, search_query=search_query))
        trace.flush()
        model = answers[0].model if answers else "-"
        return AnswerResult(mode, answers, trace, model, countries=countries)


def build_generator(api_key: str | None, model: str, temperature: float):
    return OpenAIGenerator(api_key, model, temperature) if api_key else DryRunGenerator()

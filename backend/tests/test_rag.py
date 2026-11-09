from rag.chunker import chunk_pages, is_heading
from rag.embeddings import HashingEmbedder, cosine
from rag.generator import Generation, parse_generation
from rag.loaders import PageText, load_file
from rag.pipeline import DocumentMeta
from rag.verifier import verify
from rag.vectorstore import SearchHit

from .conftest import FIXTURES


def test_heading_patterns_cover_each_country():
    assert is_heading("§ 211.22 Responsibilities of quality control unit")
    assert is_heading("Annex 11 Computerised Systems")
    assert is_heading("Chapter 4 Documentation")
    assert is_heading("제5조(품질보증)")
    assert is_heading("第十条 製造管理")
    assert not is_heading("품질보증 부서는 제조번호별로 제조기록서와 시험성적서를 검토한 뒤 출하를 승인한다.")


def test_chunks_keep_section_and_page():
    pages = load_file(FIXTURES / "kr_sample.txt")
    chunks = chunk_pages(pages, max_chars=400, overlap_chars=50)
    sections = [c.section for c in chunks]
    assert "제5조(품질보증)" in sections and "제10조(변경관리)" in sections
    # 조항이 바뀌면 이전 조항 내용이 다음 청크에 섞이지 않는다
    change = next(c for c in chunks if c.section == "제10조(변경관리)")
    assert "출하를 승인" not in change.text


def test_long_paragraph_is_split_with_overlap():
    text = " ".join(f"문장 {i}은 기록의 정확성을 확인한다." for i in range(200))
    chunks = chunk_pages([PageText(3, text)], max_chars=300, overlap_chars=40)
    assert len(chunks) > 3
    assert all(len(c.text) <= 300 + 40 + 1 for c in chunks)
    assert all(c.page == 3 for c in chunks)


def test_hash_embedder_is_deterministic_and_similar_text_scores_higher():
    e = HashingEmbedder()
    a = e.embed_query("audit trail for computerised systems")
    assert a == e.embed_query("audit trail for computerised systems")
    near = cosine(a, e.embed_query("computerised systems audit trail review"))
    far = cosine(a, e.embed_query("제조번호별 출하 승인"))
    assert near > far


def test_parse_generation_is_lenient():
    g = parse_generation('{"answer": "QP가 인증한다 [2].", "source_refs": "1", "insufficient": false}', "m")
    assert g.source_refs == [1, 2]
    g2 = parse_generation('설명 {"answer": "x", "source_refs": [3]} 끝', "m")
    assert g2.source_refs == [3]


def _hit(score):
    return SearchHit("doc1-c0", "text", score, {"country": "EU", "document_id": 1, "chunk_index": 0})


def test_verifier_reports_every_reason():
    e = HashingEmbedder()
    v = verify(Generation("답변", [], False, "m"), [_hit(0.9)], e, 0.35, 0.75)
    assert v.review_required and v.reasons == ["NO_CITATION"]

    v = verify(Generation("답변 [5]", [5], True, "m"), [_hit(0.1)], e, 0.35, 0.75)
    assert set(v.reasons) == {"LOW_RETRIEVAL_SCORE", "INVALID_CITATION", "INSUFFICIENT_CONTEXT"}

    ok = verify(Generation("답변 [1]", [1], False, "m", samples=["답변 [1]"]), [_hit(0.9)], e, 0.35, 0.75)
    assert not ok.review_required and ok.consistency == 1.0


def test_compare_mode_retrieves_per_country(pipeline):
    for i, (name, c) in enumerate([("us_sample.txt", "US"), ("eu_sample.txt", "EU"), ("kr_sample.txt", "KR")], 1):
        pipeline.ingest(str(FIXTURES / name), DocumentMeta(i, c, name))
    result = pipeline.answer("배치 출하 승인은 누가 하나요? batch release", ["US", "EU", "KR"], "compare")
    assert [a.country for a in result.answers] == ["DIFF", "US", "EU", "KR"]
    assert set(h.metadata["country"] for h in result.answers[0].hits) == {"US", "EU", "KR"}
    for a in result.answers[1:]:
        assert a.hits and all(h.metadata["country"] == a.country for h in a.hits)
    assert any(k.startswith("retrieve:") for k in result.trace.timings_ms)


def test_reingest_replaces_vectors(pipeline):
    meta = DocumentMeta(7, "EU", "eu")
    n1 = len(pipeline.ingest(str(FIXTURES / "eu_sample.txt"), meta))
    pipeline.ingest(str(FIXTURES / "eu_sample.txt"), meta)
    assert pipeline.store.count() == n1


def test_jsonl_records_keep_article_header(pipeline, tmp_path):
    import json

    recs = [
        {"id": "JP-T-art12", "country": "JP", "article_no": "第十二条", "caption": "出荷の管理", "caption_ko": "출하 관리",
         "header": "[JP] GMP省令 > 第十二条 出荷の管理 / 출하 관리", "text": "製造業者等は、ロットごとに出荷の可否を決定する。",
         "topics": ["출하 승인"]},
        {"id": "JP-T-art14", "country": "JP", "article_no": "第十四条", "caption": "変更の管理", "caption_ko": "변경관리",
         "header": "[JP] GMP省令 > 第十四条 変更の管理 / 변경관리", "text": "変更の影響を評価する。" * 200, "topics": []},
    ]
    p = tmp_path / "jp.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")
    chunks = pipeline.ingest(str(p), DocumentMeta(9, "JP", "jp"))
    assert chunks[0].record_id == "JP-T-art12" and chunks[0].text.startswith("[JP] GMP省令 > 第十二条")
    long_parts = [c for c in chunks if c.record_id == "JP-T-art14"]
    assert len(long_parts) > 1 and all(c.text.startswith("[JP] GMP省令 > 第十四条") for c in long_parts)
    hits = pipeline.search("출하 관리 出荷", ["JP"], 3)
    assert hits[0].metadata["record_id"] == "JP-T-art12" and hits[0].metadata["topics"] == "출하 승인"


def test_query_expansion_adds_foreign_terms():
    from rag.glossary import expand_query

    q = expand_query("일탈이 발생하면 어떻게 처리하나요?")
    assert "deviation" in q and "逸脱" in q
    assert expand_query("날씨 어때?") == "날씨 어때?"


def test_keyword_tokenizer_and_hybrid_finds_exact_term(pipeline):
    from rag.keyword import rrf, tokenize

    assert "deviations" in tokenize("Written procedures; deviations") and "기록" in tokenize("점검기록")
    assert rrf([["a", "b"], ["b", "c"]])[0] == "b"
    pipeline.ingest(str(FIXTURES / "us_sample.txt"), DocumentMeta(1, "US", "us"))
    pipeline.ingest(str(FIXTURES / "eu_sample.txt"), DocumentMeta(2, "EU", "eu"))
    hits = pipeline.search("audit trail", ["EU"], 2)
    assert hits and all(h.metadata["country"] == "EU" for h in hits) and "Audit trail" in hits[0].text
    assert all(-1.0 <= h.score <= 1.0 for h in hits)


def test_intent_detects_country_comparison():
    from rag.intent import detect

    i = detect("출하 승인에 대해 한국과 미국은 어떻게 달라?")
    assert i.is_compare and i.countries == ["KR", "US"] and i.topic == "출하 승인"
    i = detect("미국 FDA와 한국 식약처의 일탈 처리 비교해줘")
    assert i.countries == ["US", "KR"] and i.topic == "일탈 처리"
    assert not detect("변경관리 절차는?").is_compare


def test_single_mode_compare_question_switches_to_compare(pipeline):
    for i, (name, c) in enumerate([("us_sample.txt", "US"), ("eu_sample.txt", "EU"), ("kr_sample.txt", "KR")], 1):
        pipeline.ingest(str(FIXTURES / name), DocumentMeta(i, c, name))
    result = pipeline.answer("배치 출하 승인은 한국과 미국이 어떻게 달라?", ["US", "EU", "KR"], "single")
    assert result.mode == "compare" and result.countries == ["KR", "US"]
    assert [a.country for a in result.answers] == ["DIFF", "KR", "US"]


def test_single_country_question_searches_only_that_country(pipeline):
    for i, (name, c) in enumerate([("us_sample.txt", "US"), ("eu_sample.txt", "EU"), ("kr_sample.txt", "KR")], 1):
        pipeline.ingest(str(FIXTURES / name), DocumentMeta(i, c, name))
    result = pipeline.answer("미국 FDA에서 배치 출하 승인은 누가 해?", ["US", "EU", "KR"], "single")
    assert result.mode == "single" and result.countries == ["US"]
    assert all(h.metadata["country"] == "US" for h in result.answers[0].hits)

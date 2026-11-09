"""질문 처리: 캐시 확인 → RAG 실행 → 대화·인용 저장 → 응답 조립."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag.pipeline import RagPipeline
from rag.verifier import REASONS

from ..models import AnswerCache, ChatMessage, ChatSession, Chunk, Document, MessageCitation, now
from ..schemas import AnswerOut, AskRequest, AskResponse, CitationOut


def data_version(db: Session) -> str:
    """색인된 문서 구성이 바뀌면 값이 바뀐다 → 캐시가 자동으로 무효화된다."""
    row = db.execute(
        select(func.count(Document.id), func.max(Document.updated_at)).where(Document.status == "indexed")
    ).one()
    return hashlib.sha256(f"{row[0]}|{row[1]}".encode()).hexdigest()[:16]


def cache_key(question: str, countries: list[str], mode: str, version: str, model: str) -> str:
    norm = " ".join(question.lower().split())
    raw = f"{norm}|{','.join(sorted(countries))}|{mode}|{version}|{model}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _chunk_lookup(db: Session, hits) -> dict[tuple[int, int], Chunk]:
    keys = {(int(h.metadata["document_id"]), int(h.metadata["chunk_index"])) for h in hits}
    if not keys:
        return {}
    doc_ids = {k[0] for k in keys}
    rows = db.scalars(select(Chunk).where(Chunk.document_id.in_(doc_ids))).all()
    return {(c.document_id, c.chunk_index): c for c in rows if (c.document_id, c.chunk_index) in keys}


def _citations(hits, cited_refs, lookup) -> list[CitationOut]:
    out = []
    for i, h in enumerate(hits, start=1):
        m = h.metadata
        ch = lookup.get((int(m["document_id"]), int(m["chunk_index"])))
        page = m.get("page")
        out.append(
            CitationOut(
                ref_no=i, cited=i in cited_refs, chunk_id=ch.id if ch else None,
                document_id=int(m["document_id"]), country=m.get("country", ""),
                document_title=m.get("title", ""), doc_code=m.get("doc_code", ""), version=m.get("version", ""),
                effective_date=m.get("effective_date", ""), section=m.get("section", ""),
                page=None if page in (-1, "", None) else int(page), source_url=m.get("source_url", ""),
                score=h.score, snippet=h.text[:300],
            )
        )
    return out


def ask(db: Session, pipeline: RagPipeline, req: AskRequest, countries: list[str], ttl_days: int) -> AskResponse:
    started = time.perf_counter()

    # 1) 세션
    session = db.get(ChatSession, req.session_id) if req.session_id else None
    if req.session_id and not session:
        raise LookupError("대화 세션을 찾을 수 없습니다.")
    if not session:
        session = ChatSession(title=req.question[:60])
        db.add(session)
        db.flush()

    user_msg = ChatMessage(
        session_id=session.id, role="user", content=req.question,
        countries=",".join(countries), mode=req.mode,
    )
    db.add(user_msg)
    db.flush()

    # 2) 캐시
    model_name = getattr(pipeline.generator, "model", "-")
    version = data_version(db)
    key = cache_key(req.question, countries, req.mode, version, model_name)
    cached_payload = None
    if req.use_cache and not pipeline.is_dry_run:
        hit = db.scalar(select(AnswerCache).where(AnswerCache.cache_key == key, AnswerCache.expires_at > now()))
        if hit:
            cached_payload = json.loads(hit.response_json)

    if cached_payload:
        answers = [AnswerOut(**a) for a in cached_payload["answers"]]
        timings, trace_id, model = {}, "", cached_payload["model"]
        resolved_mode = cached_payload.get("mode", req.mode)
        countries = cached_payload.get("countries", countries)
    else:
        result = pipeline.answer(req.question, countries, req.mode)
        lookup = _chunk_lookup(db, [h for a in result.answers for h in a.hits])
        answers = [
            AnswerOut(
                country=a.country, answer=a.answer, citations=_citations(a.hits, a.cited_refs, lookup),
                review_required=a.verdict.review_required, review_reasons=a.verdict.reasons,
                review_messages=a.verdict.messages, top_score=a.verdict.top_score,
                consistency=a.verdict.consistency,
            )
            for a in result.answers
        ]
        timings, trace_id, model = result.trace.timings_ms, result.trace.id, result.model
        # 질문에서 '한국과 미국의 차이'를 읽어 비교 모드로 바뀌었을 수 있다
        resolved_mode, countries = result.mode, result.countries or countries
        # dry-run 결과는 캐시에 넣지 않는다 (테스트용 응답이 실제 사용자에게 새어 나가는 것 방지)
        if not pipeline.is_dry_run:
            db.query(AnswerCache).filter(AnswerCache.cache_key == key).delete()
            db.add(
                AnswerCache(
                    cache_key=key, data_version=version, expires_at=now() + timedelta(days=ttl_days),
                    response_json=json.dumps({"answers": [a.model_dump() for a in answers], "model": model,
                                              "mode": resolved_mode, "countries": countries}, ensure_ascii=False),
                )
            )

    latency = int((time.perf_counter() - started) * 1000)
    user_msg.mode, user_msg.countries = resolved_mode, ",".join(countries)  # 대화 다시 열 때 비교 화면으로 보이도록

    # 3) 답변·인용 저장
    for a in answers:
        msg = ChatMessage(
            session_id=session.id, role="assistant", country=a.country, content=a.answer,
            countries=",".join(countries), mode=resolved_mode, review_required=a.review_required,
            review_reasons=",".join(a.review_reasons), top_score=a.top_score, consistency=a.consistency,
            model=model, latency_ms=latency, trace_id=trace_id,
        )
        for c in a.citations:
            msg.citations.append(MessageCitation(chunk_id=c.chunk_id, ref_no=c.ref_no, cited=c.cited, score=c.score))
        db.add(msg)
        db.flush()
        a.message_id = msg.id
    db.commit()

    return AskResponse(
        session_id=session.id, question_message_id=user_msg.id, mode=resolved_mode, countries=countries,
        answers=answers, model=model, cached=bool(cached_payload), latency_ms=latency,
        timings_ms=timings, trace_id=trace_id,
    )


def message_citations_out(msg: ChatMessage) -> list[CitationOut]:
    out = []
    for c in msg.citations:
        ch = c.chunk
        doc = ch.document if ch else None
        out.append(
            CitationOut(
                ref_no=c.ref_no, cited=c.cited, chunk_id=c.chunk_id, document_id=doc.id if doc else None,
                country=doc.country if doc else "", document_title=doc.title if doc else "(삭제된 문서)",
                doc_code=doc.doc_code if doc else "", version=doc.version if doc else "",
                effective_date=doc.effective_date if doc else "", section=ch.section if ch else "",
                page=ch.page if ch else None, source_url=doc.source_url if doc else "", score=c.score,
                snippet=ch.text[:300] if ch else "",
            )
        )
    return out


def reason_messages(codes: str) -> list[str]:
    return [REASONS.get(c, c) for c in codes.split(",") if c]


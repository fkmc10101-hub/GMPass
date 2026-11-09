from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag.countries import normalize_codes
from rag.pipeline import RagPipeline

from ..config import Settings
from ..deps import get_db, get_pipeline, get_settings_dep
from ..models import ChatMessage, ChatSession, Feedback
from ..schemas import (
    AskRequest, AskResponse, FeedbackIn, FeedbackOut, MessageOut, SearchHitOut, SearchRequest,
    SessionDetailOut, SessionOut,
)
from ..services import chat_service

router = APIRouter(prefix="/api", tags=["chat"])


def _codes(codes: list[str]) -> list[str]:
    try:
        return normalize_codes(codes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/chat/ask", response_model=AskResponse, summary="질문하기 (단일 답변 / 국가별 비교)")
def ask(
    req: AskRequest,
    db: Session = Depends(get_db),
    pipeline: RagPipeline = Depends(get_pipeline),
    settings: Settings = Depends(get_settings_dep),
):
    countries = _codes(req.countries)
    if req.mode == "compare" and len(countries) < 2:
        raise HTTPException(status_code=422, detail="비교 모드는 국가를 2개 이상 선택해야 합니다.")
    try:
        return chat_service.ask(db, pipeline, req, countries, settings.cache_ttl_days)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/search", response_model=list[SearchHitOut], summary="검색만 실행 (답변 생성 없이 근거 확인)")
def search(req: SearchRequest, pipeline: RagPipeline = Depends(get_pipeline)):
    hits = pipeline.search(req.query, _codes(req.countries), req.top_k)
    return [
        SearchHitOut(
            vector_id=h.vector_id, country=h.metadata.get("country", ""),
            document_id=int(h.metadata["document_id"]), document_title=h.metadata.get("title", ""),
            section=h.metadata.get("section", ""),
            page=None if h.metadata.get("page") in (-1, "", None) else int(h.metadata["page"]),
            score=h.score, text=h.text,
        )
        for h in hits
    ]


@router.get("/chat/sessions", response_model=list[SessionOut], summary="대화 목록")
def list_sessions(db: Session = Depends(get_db)):
    rows = db.execute(
        select(ChatSession, func.count(ChatMessage.id))
        .outerjoin(ChatMessage)
        .group_by(ChatSession.id)
        .order_by(ChatSession.id.desc())
    ).all()
    return [SessionOut(id=s.id, title=s.title, created_at=s.created_at, message_count=n) for s, n in rows]


@router.get("/chat/sessions/{session_id}", response_model=SessionDetailOut, summary="대화 상세 (메시지·인용 포함)")
def get_session(session_id: int, db: Session = Depends(get_db)):
    s = db.get(ChatSession, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="대화 세션을 찾을 수 없습니다.")
    return SessionDetailOut(
        id=s.id, title=s.title, created_at=s.created_at,
        messages=[
            MessageOut(
                id=m.id, role=m.role, country=m.country, content=m.content,
                countries=[c for c in m.countries.split(",") if c], mode=m.mode,
                review_required=m.review_required,
                review_reasons=[r for r in m.review_reasons.split(",") if r],
                citations=chat_service.message_citations_out(m), created_at=m.created_at,
            )
            for m in s.messages
        ],
    )


@router.delete("/chat/sessions/{session_id}", status_code=204, summary="대화 삭제")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = db.get(ChatSession, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="대화 세션을 찾을 수 없습니다.")
    db.delete(s)
    db.commit()


@router.post("/messages/{message_id}/feedback", response_model=FeedbackOut, status_code=201, summary="답변 평가")
def feedback(message_id: int, body: FeedbackIn, db: Session = Depends(get_db)):
    m = db.get(ChatMessage, message_id)
    if not m or m.role != "assistant":
        raise HTTPException(status_code=404, detail="평가할 답변을 찾을 수 없습니다.")
    fb = Feedback(message_id=message_id, rating=body.rating, comment=body.comment)
    db.add(fb)
    db.commit()
    db.refresh(fb)
    return fb

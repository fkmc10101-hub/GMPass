"""근거 원문(영어·일본어) → 한국어 번역.

답변 자체는 처음부터 한국어로 생성되지만, 근거로 보여 주는 원문 조항은 원어 그대로다.
사용자가 '한국어 번역 보기'를 누를 때만 LLM으로 번역하고, 결과를 DB에 저장해 두 번째부터는 비용 없이 보여 준다.
"""

import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.pipeline import RagPipeline

from ..deps import get_db, get_pipeline
from ..models import Chunk, Translation
from ..schemas import TranslateIn, TranslateOut

router = APIRouter(prefix="/api", tags=["translate"])


@router.post("/translate", response_model=TranslateOut, summary="근거 원문을 한국어로 번역 (결과 캐시)")
def translate(body: TranslateIn, db: Session = Depends(get_db), pipeline: RagPipeline = Depends(get_pipeline)):
    chunk = db.get(Chunk, body.chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="근거 청크를 찾을 수 없습니다.")
    lang = chunk.document.language or ""
    if lang == "ko":
        return TranslateOut(chunk_id=chunk.id, source_language=lang, original=chunk.text, text_ko=chunk.text,
                            model="-", cached=True, notice="원문이 한국어입니다.")

    digest = hashlib.sha256(chunk.text.encode()).hexdigest()
    hit = db.scalar(select(Translation).where(Translation.chunk_id == chunk.id))
    if hit and hit.source_hash == digest:
        return TranslateOut(chunk_id=chunk.id, source_language=lang, original=chunk.text, text_ko=hit.text_ko,
                            model=hit.model, cached=True)

    try:
        text_ko = pipeline.generator.translate(chunk.text)
    except RuntimeError as e:  # dry-run (API 키 없음)
        raise HTTPException(status_code=503, detail=str(e)) from e
    model = getattr(pipeline.generator, "model", "-")
    if hit:
        hit.source_hash, hit.text_ko, hit.model = digest, text_ko, model
    else:
        db.add(Translation(chunk_id=chunk.id, source_hash=digest, text_ko=text_ko, model=model))
    db.commit()
    return TranslateOut(chunk_id=chunk.id, source_language=lang, original=chunk.text, text_ko=text_ko,
                        model=model, cached=False)

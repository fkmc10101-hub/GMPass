from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from rag.countries import JURISDICTIONS
from rag.pipeline import RagPipeline

from ..config import Settings
from ..deps import get_db, get_pipeline, get_settings_dep
from ..models import Document
from ..schemas import CountryOut, HealthOut

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/health", response_model=HealthOut, summary="서버 상태 확인")
def health(pipeline: RagPipeline = Depends(get_pipeline), settings: Settings = Depends(get_settings_dep)):
    return HealthOut(
        status="ok",
        dry_run=pipeline.is_dry_run,
        llm_model=getattr(pipeline.generator, "model", "-"),
        embedding_model=pipeline.embedder.name,
        indexed_chunks=pipeline.store.count(),
    )


@router.get("/countries", response_model=list[CountryOut], summary="지원 국가·기구 목록")
def countries(db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(Document.country, func.count(Document.id)).where(Document.status == "indexed").group_by(Document.country)
        ).all()
    )
    return [
        CountryOut(
            code=j.code, name_ko=j.name_ko, authority=j.authority, main_documents=list(j.main_documents),
            language=j.language, indexed_documents=counts.get(j.code, 0),
        )
        for j in JURISDICTIONS.values()
    ]

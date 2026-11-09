import re

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.countries import JURISDICTIONS
from rag.pipeline import RagPipeline

from ..config import Settings
from ..deps import get_db, get_pipeline, get_settings_dep, require_admin
from ..models import Chunk, Document
from ..schemas import ChunkOut, DocumentOut
from ..services import document_service

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _get_doc(db: Session, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return doc


@router.get("", response_model=list[DocumentOut], summary="문서 목록")
def list_documents(
    country: str | None = Query(default=None, description="국가 코드로 필터"),
    status: str | None = Query(default=None, pattern="^(pending|indexed|failed)$"),
    db: Session = Depends(get_db),
):
    q = select(Document).order_by(Document.country, Document.id)
    if country:
        q = q.where(Document.country == country.upper())
    if status:
        q = q.where(Document.status == status)
    return db.scalars(q).all()


@router.post("", response_model=DocumentOut, status_code=202, summary="문서 등록 (업로드 후 백그라운드 색인)",
             dependencies=[Depends(require_admin)])
def upload_document(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    country: str = Form(...),
    title: str = Form(..., min_length=1, max_length=300),
    doc_code: str = Form(""),
    version: str = Form(""),
    effective_date: str = Form("", description="YYYY-MM-DD"),
    language: str = Form(""),
    source_url: str = Form(""),
    db: Session = Depends(get_db),
    pipeline: RagPipeline = Depends(get_pipeline),
    settings: Settings = Depends(get_settings_dep),
):
    country = country.upper()
    if country not in JURISDICTIONS:
        raise HTTPException(status_code=422, detail=f"지원하지 않는 국가 코드입니다: {country}")
    if effective_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective_date):
        raise HTTPException(status_code=422, detail="시행일은 YYYY-MM-DD 형식이어야 합니다.")
    size = getattr(file, "size", None)
    if size and size > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"파일은 {settings.max_upload_mb}MB 이하만 등록할 수 있습니다.")

    meta = dict(
        country=country, title=title.strip(), doc_code=doc_code.strip(), version=version.strip(),
        effective_date=effective_date, language=(language or JURISDICTIONS[country].language).strip(),
        source_url=source_url.strip(),
    )
    try:
        doc = document_service.save_upload(db, settings.upload_dir, file.file, file.filename or "document", meta)
    except document_service.DuplicateDocument as e:
        raise HTTPException(status_code=409, detail=f"같은 파일이 이미 등록돼 있습니다. (document_id={e.existing_id})") from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    background.add_task(
        document_service.index_document, request.app.state.session_factory, pipeline, settings.upload_dir, doc.id
    )
    return doc


@router.get("/{document_id}", response_model=DocumentOut, summary="문서 상세")
def get_document(document_id: int, db: Session = Depends(get_db)):
    return _get_doc(db, document_id)


@router.get("/{document_id}/chunks", response_model=list[ChunkOut], summary="문서 청크 목록 (청킹 결과 확인)")
def get_chunks(
    document_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    _get_doc(db, document_id)
    return db.scalars(
        select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index).offset(offset).limit(limit)
    ).all()


@router.post("/{document_id}/reindex", response_model=DocumentOut, status_code=202, summary="재색인",
             dependencies=[Depends(require_admin)])
def reindex(
    document_id: int,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    pipeline: RagPipeline = Depends(get_pipeline),
    settings: Settings = Depends(get_settings_dep),
):
    doc = _get_doc(db, document_id)
    doc.status, doc.error_message = "pending", ""
    db.commit()
    background.add_task(
        document_service.index_document, request.app.state.session_factory, pipeline, settings.upload_dir, doc.id
    )
    return doc


@router.delete("/{document_id}", status_code=204, summary="문서 삭제 (벡터·원문 파일 함께 삭제)",
               dependencies=[Depends(require_admin)])
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    pipeline: RagPipeline = Depends(get_pipeline),
    settings: Settings = Depends(get_settings_dep),
):
    document_service.delete_document(db, pipeline, settings.upload_dir, _get_doc(db, document_id))

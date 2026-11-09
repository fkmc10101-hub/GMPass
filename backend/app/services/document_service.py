"""문서 등록·색인·삭제."""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.loaders import SUPPORTED_EXTENSIONS, file_sha256
from rag.pipeline import DocumentMeta, RagPipeline
from rag.vectorstore import VectorStore

from ..models import Chunk, Document

log = logging.getLogger("gmpass.documents")


class DuplicateDocument(Exception):
    def __init__(self, existing_id: int):
        self.existing_id = existing_id


def _safe_name(name: str) -> str:
    name = Path(name).name
    return re.sub(r"[^\w.\-가-힣ぁ-んァ-ン一-龥() ]", "_", name)[:200] or "document"


def save_upload(db: Session, upload_dir: str, fileobj, filename: str, meta: dict) -> Document:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"PDF·TXT·MD·HTML·JSONL만 등록할 수 있습니다. (받은 형식: {ext or '없음'})")

    Path(upload_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=upload_dir, suffix=ext) as tmp:
        shutil.copyfileobj(fileobj, tmp)
        tmp_path = Path(tmp.name)

    digest = file_sha256(tmp_path)
    existing = db.scalar(select(Document).where(Document.file_hash == digest))
    if existing:
        tmp_path.unlink(missing_ok=True)
        raise DuplicateDocument(existing.id)

    final = Path(upload_dir) / f"{digest[:12]}_{_safe_name(filename)}"
    tmp_path.replace(final)
    doc = Document(file_name=final.name, file_hash=digest, status="pending", **meta)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def index_document(session_factory, pipeline: RagPipeline, upload_dir: str, document_id: int) -> None:
    """백그라운드 작업에서 호출된다. 요청 세션과 별개의 DB 세션을 연다."""
    db: Session = session_factory()
    try:
        doc = db.get(Document, document_id)
        if not doc:
            return
        try:
            meta = DocumentMeta(
                document_id=doc.id, country=doc.country, title=doc.title, doc_code=doc.doc_code,
                version=doc.version, effective_date=doc.effective_date, language=doc.language,
                source_url=doc.source_url,
            )
            chunks = pipeline.ingest(str(Path(upload_dir) / doc.file_name), meta)
            doc.chunks.clear()
            db.flush()
            for c in chunks:
                doc.chunks.append(
                    Chunk(
                        chunk_index=c.index, section=c.section or "", page=c.page, text=c.text,
                        char_count=c.char_count, vector_id=VectorStore.vector_id(doc.id, c.index),
                    )
                )
            doc.status, doc.chunk_count, doc.error_message = "indexed", len(chunks), ""
        except Exception as exc:  # noqa: BLE001
            log.exception("문서 색인 실패: id=%s", document_id)
            doc.status, doc.error_message = "failed", str(exc)[:1000]
        db.commit()
    finally:
        db.close()


def delete_document(db: Session, pipeline: RagPipeline, upload_dir: str, doc: Document) -> None:
    pipeline.store.delete_document(doc.id)
    pipeline._bm25 = None  # 키워드 색인 갱신
    (Path(upload_dir) / doc.file_name).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()

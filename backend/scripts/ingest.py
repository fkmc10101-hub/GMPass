"""여러 문서를 한 번에 등록하는 스크립트.

사용법 (backend 폴더에서):
    python -m scripts.ingest --processed               # data/processed/*.jsonl (권장: 조항 단위 레코드)
    python -m scripts.ingest ../data/raw/manifest.csv  # 원문 파일을 그대로 등록

manifest.csv 열: file,country,title,doc_code,version,effective_date,language,source_url
- file 은 manifest.csv 와 같은 폴더 기준 상대경로
- 이미 등록된 파일(내용이 같은 파일)은 건너뛴다
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.database import Base, make_engine, make_session_factory  # noqa: E402
from app.main import build_pipeline  # noqa: E402
from app.services import document_service  # noqa: E402
from app.models import Document  # noqa: E402


def processed_rows() -> list[dict]:
    """data/processed/*.jsonl 의 첫 레코드에서 문서 메타데이터를 읽어 manifest 행처럼 만든다."""
    import json

    base = Path(__file__).resolve().parents[2] / "data" / "processed"
    rows = []
    for p in sorted(base.glob("*.jsonl")):
        with open(p, encoding="utf-8") as f:
            first = json.loads(f.readline())
        rows.append({
            "file": str(p), "country": first["country"], "title": f"{first['doc_code']} — {first['title']}"[:300],
            "doc_code": first["doc_code"], "version": first.get("version", ""), "effective_date": "",
            "language": first.get("lang", ""), "source_url": first.get("source_url", ""),
        })
    return rows


def main(manifest: str | None) -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    sf = make_session_factory(engine)
    pipeline = build_pipeline(settings)
    if manifest:
        base = Path(manifest).parent
        with open(manifest, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    else:
        base = Path("/")
        rows = processed_rows()

    for row in rows:
        path = Path(row["file"]) if Path(row["file"]).is_absolute() else base / row["file"]
        if not path.exists():
            print(f"[건너뜀] 파일 없음: {path}")
            continue
        meta = {k: (row.get(k) or "").strip() for k in
                ("country", "title", "doc_code", "version", "effective_date", "language", "source_url")}
        meta["country"] = meta["country"].upper()
        db = sf()
        if not manifest:
            # 재가공한 JSONL은 내용이 바뀌어 해시가 달라진다 → 같은 문서 코드의 이전 판을 지우고 새로 등록
            from sqlalchemy import select

            old = db.scalars(select(Document).where(Document.country == meta["country"],
                                                    Document.doc_code == meta["doc_code"])).all()
            for d in old:
                document_service.delete_document(db, pipeline, settings.upload_dir, d)
                print(f"[교체] 이전 판 삭제: {d.title}")
        try:
            with open(path, "rb") as fh:
                doc = document_service.save_upload(db, settings.upload_dir, fh, path.name, meta)
            doc_id = doc.id
        except document_service.DuplicateDocument as e:
            print(f"[건너뜀] 이미 등록됨 (id={e.existing_id}): {path.name}")
            continue
        finally:
            db.close()
        document_service.index_document(sf, pipeline, settings.upload_dir, doc_id)
        db = sf()
        d = db.get(Document, doc_id)
        print(f"[{d.status}] {d.country} {d.title} — 청크 {d.chunk_count}개 {d.error_message}")
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(None if sys.argv[1] == "--processed" else sys.argv[1])

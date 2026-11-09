"""원문 파일을 (페이지 번호, 텍스트) 목록으로 읽어 온다.

지원 형식: PDF, TXT, MD, HTML
+ JSONL: scripts/prepare_sources.py 가 만든 조항 단위 레코드 (load_records)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".html", ".htm", ".jsonl"}


@dataclass
class PageText:
    page: int | None  # PDF가 아니면 None
    text: str


class _HTMLTextExtractor(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_file(path: str | Path) -> list[PageText]:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {ext}")

    if ext == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = _clean(page.extract_text() or "")
            if text:
                pages.append(PageText(i, text))
        if not pages:
            raise ValueError("PDF에서 텍스트를 추출하지 못했습니다. 스캔본이면 OCR이 필요합니다.")
        return pages

    raw = path.read_text(encoding="utf-8", errors="replace")
    if ext in (".html", ".htm"):
        parser = _HTMLTextExtractor()
        parser.feed(raw)
        raw = "".join(parser.parts)
    return [PageText(None, _clean(raw))]


def load_records(path: str | Path) -> list[dict]:
    """조항 단위 JSONL(prepare_sources.py 결과)을 읽는다. 필수 필드: id, text, header."""
    import json

    records = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            missing = [k for k in ("id", "text", "header") if not rec.get(k)]
            if missing:
                raise ValueError(f"{n}번째 줄에 필수 필드가 없습니다: {missing}")
            records.append(rec)
    if not records:
        raise ValueError("JSONL에 레코드가 없습니다.")
    return records

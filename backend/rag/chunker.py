"""조항·장·부속서 제목을 인식해 섹션 정보를 보존하며 청크로 나눈다.

GMP 문서는 '어느 조항에 있는 내용인가'가 근거의 핵심이므로,
청크마다 직전에 나온 조항 제목(section)과 페이지를 함께 저장한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .loaders import PageText

# 국가별 조항·제목 패턴 (줄 시작 기준)
HEADING_PATTERNS = [
    r"^§\s*\d{3}\.\d+[a-z]?\b.*",                 # US: § 211.22 Responsibilities of quality control unit
    r"^(Sec\.|Section)\s*\d{3}\.\d+.*",             # US: Sec. 211.22
    r"^(CHAPTER|Chapter)\s+\d+\b.*",                # EU/PIC/S: Chapter 4 Documentation
    r"^(ANNEX|Annex)\s+\d+[A-Z]?\b.*",              # EU/PIC/S: Annex 11
    r"^(PART|Part)\s+[IVX]+\b.*",                   # EU Part I/II
    r"^Article\s+\d+.*",                            # EU Directive
    r"^제\s*\d+\s*조(의\s*\d+)?\s*(\(.*?\))?.*",      # KR: 제5조(제조관리)
    r"^제\s*\d+\s*장\s+.*",                           # KR: 제2장 품질관리
    r"^第[一二三四五六七八九十百〇0-9０-９]+条.*",          # JP: 第十条
    r"^第[一二三四五六七八九十百〇0-9０-９]+章.*",          # JP: 第二章
    r"^\d+(\.\d+){0,3}\.?\s+[A-Z가-힣ぁ-んァ-ン一-龥].{0,80}$",  # 4.1 General / 2.3 문서관리
]
_HEADING_RE = re.compile("|".join(f"(?:{p})" for p in HEADING_PATTERNS))


@dataclass
class Chunk:
    index: int
    text: str
    section: str | None
    page: int | None
    record_id: str = ""  # 조항 단위 레코드에서 온 청크면 레코드 ID
    topics: str = ""     # 주제 태그 (쉼표 구분)

    @property
    def char_count(self) -> int:
        return len(self.text)


def is_heading(line: str) -> bool:
    line = line.strip()
    return 0 < len(line) <= 120 and bool(_HEADING_RE.match(line))


def _split_long(text: str, max_chars: int) -> list[str]:
    """한 문단이 max_chars보다 길면 문장 경계에서 자른다."""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s*", text)
    out, buf = [], ""
    for s in sentences:
        if not s:
            continue
        if len(buf) + len(s) + 1 > max_chars and buf:
            out.append(buf.strip())
            buf = ""
        while len(s) > max_chars:  # 문장 자체가 너무 긴 경우
            out.append(s[:max_chars])
            s = s[max_chars:]
        buf += (" " if buf else "") + s
    if buf.strip():
        out.append(buf.strip())
    return out


def chunk_pages(pages: list[PageText], max_chars: int = 1000, overlap_chars: int = 150) -> list[Chunk]:
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars는 max_chars보다 작아야 합니다.")

    chunks: list[Chunk] = []
    section: str | None = None
    buf = ""
    buf_section: str | None = None
    buf_page: int | None = None

    def flush():
        nonlocal buf
        text = buf.strip()
        if text:
            chunks.append(Chunk(len(chunks), text, buf_section, buf_page))
            # 다음 청크 앞에 겹침(overlap)을 남겨 문맥이 끊기지 않게 한다
            buf = text[-overlap_chars:] if overlap_chars else ""
        else:
            buf = ""

    for page in pages:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n(?=\S)", page.text) if p.strip()]
        for para in paragraphs:
            first_line = para.split("\n", 1)[0]
            if is_heading(first_line):
                # 새 조항이 시작되면 이전 청크를 닫고 겹침 없이 새로 시작
                if buf.strip():
                    flush()
                buf = ""
                section = first_line.strip()[:200]
            for piece in _split_long(para, max_chars):
                if not buf.strip():
                    buf_section, buf_page = section, page.page
                if len(buf) + len(piece) + 1 > max_chars:
                    flush()
                    buf_section, buf_page = section, page.page
                buf += ("\n" if buf else "") + piece
    if buf.strip():
        # 마지막 청크가 겹침만 남은 경우는 버린다
        if not chunks or buf.strip() != chunks[-1].text[-overlap_chars:].strip():
            chunks.append(Chunk(len(chunks), buf.strip(), buf_section, buf_page))
    return chunks


def chunk_records(records: list[dict], max_chars: int = 1000, overlap_chars: int = 150) -> list[Chunk]:
    """조항 1개 = 청크 1개가 기본. 긴 조항만 문장 경계에서 나누고, 조각마다 조항 위치(header)를 앞에 붙인다.

    header 예: [JP] GMP省令 > 第二章 … > 第十二条 製造所からの出荷の管理 / 제조소 출하 관리(출하 승인)
    → 짧은 조각도 '어느 나라 어느 조항인지'와 함께 임베딩·검색된다.
    """
    chunks: list[Chunk] = []
    for rec in records:
        header = rec["header"]
        section = f"{rec.get('article_no', '')} {rec.get('caption_ko') or rec.get('caption', '')}".strip()
        body_limit = max(200, max_chars - len(header) - 1)
        pieces = _split_long(rec["text"], body_limit)
        for i, piece in enumerate(pieces):
            if i > 0 and overlap_chars:
                piece = pieces[i - 1][-overlap_chars:] + " " + piece
            chunks.append(Chunk(
                index=len(chunks), text=f"{header}\n{piece}", section=section[:200], page=rec.get("page"),
                record_id=rec["id"], topics=",".join(rec.get("topics", [])),
            ))
    return chunks

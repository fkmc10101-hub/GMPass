"""GMP 원문(raw) → 조항 단위 레코드(processed JSONL) 변환.

사용법 (backend 폴더에서):
    python -m scripts.prepare_sources            # data/raw/sources.yaml 에 적힌 원문을 모두 변환
    python -m scripts.prepare_sources --check    # 변환 후 조항 수·빈 조항·중복 ID 점검만 출력

결과:
    data/processed/<문서ID>.jsonl     조항 1개 = 1줄 (GMPass 색인 입력)
    data/processed/_review.xlsx       사람이 검토할 수 있도록 전체 레코드를 표로 정리

설계 원칙
- raw는 절대 수정하지 않는다. 파싱이 틀리면 이 스크립트를 고쳐 다시 만든다.
- 조항 경계는 '원문 구조'(XML 태그, 조항 번호 패턴)로만 정한다. 글자 수로 자르는 것은 색인 단계에서 한다.
- PDF는 pypdf의 layout 모드로 읽는다. 기본 모드는 eCFR PDF에서 조항 순서가 뒤섞이는 문제가 확인됐다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
sys.path.insert(0, str(ROOT / "backend"))

from scripts.topics import tag_topics  # noqa: E402
from scripts.captions_ko import CAPTIONS_KO  # noqa: E402


@dataclass
class Record:
    id: str
    country: str
    doc_id: str
    doc_code: str
    title: str
    version: str
    source_url: str
    path: list[str]
    article_no: str
    caption: str
    caption_ko: str
    text: str
    lang: str
    topics: list[str] = field(default_factory=list)
    page: int | None = None

    def header(self) -> str:
        """임베딩할 때 본문 앞에 붙일 위치 정보 (검색 정확도를 높인다)."""
        cap = self.caption
        if self.caption_ko and self.caption_ko != self.caption:
            cap = f"{self.caption} / {self.caption_ko}"
        crumbs = " > ".join([self.doc_code, *self.path])
        return f"[{self.country}] {crumbs} > {self.article_no} {cap}".strip()


# ---------------------------------------------------------------- 공통 유틸
TABLE_GAPS: set[tuple[int, str]] = set()  # 표의 행처럼 보이는 줄 (칸 맞춤용 넓은 공백이 있는 줄)


def _pdf_lines(path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    out: list[tuple[int, str]] = []
    for pno, page in enumerate(PdfReader(str(path)).pages, start=1):
        text = page.extract_text(extraction_mode="layout") or ""
        for raw in text.splitlines():
            line = re.sub(r"[ \t\u00a0]{2,}", " ", raw).strip()
            if line:
                out.append((pno, line))
                # 칸을 맞추느라 생긴 8칸 이상의 공백이 있으면 표의 행일 가능성이 높다
                if re.search(r"\S {8,}\S", raw.strip()):
                    TABLE_GAPS.add((pno, line))
    return out


_HANGUL = re.compile(r"[가-힣]")


def _join_korean(lines: list[str]) -> str:
    """PDF 줄바꿈으로 끊긴 한국어 문장을 잇는다. 새 항목 기호(가. 1) (1) 등)로 시작하는 줄은 새 줄로 둔다."""
    item = re.compile(r"^([가-힣]\.|\d+\)|\(\d+\)|[①-⑳]|※|-\s|\d+(\.\d+)*\.?\s*[가-힣A-Za-z(])")
    out: list[str] = []
    for ln in lines:
        if out and not item.match(ln):
            prev = out[-1]
            sep = "" if (_HANGUL.search(prev[-1:]) and _HANGUL.search(ln[:1])) else " "
            out[-1] = prev + sep + ln
        else:
            out.append(ln)
    return "\n".join(out)


def _clean(s: str) -> str:
    s = s.replace("ᆞ", "·").replace("　", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{2,}", "\n", s).strip()


# ---------------------------------------------------------------- 일본: e-Gov 법령 XML
def parse_jp_xml(path: Path, meta: dict) -> list[Record]:
    root = ET.parse(path).getroot()
    law_body = root.find(".//MainProvision")
    recs: list[Record] = []

    def txt(el) -> str:
        return "".join(el.itertext()).strip() if el is not None else ""

    def walk(el, path_titles: list[str]):
        for child in el:
            tag = child.tag
            if tag in ("Chapter", "Section", "Subsection", "Division"):
                title = txt(child.find(f"{tag}Title"))
                walk(child, path_titles + [title.replace("　", " ")])
            elif tag == "Article":
                art_no = txt(child.find("ArticleTitle"))
                caption = txt(child.find("ArticleCaption")).strip("（）()")
                parts: list[str] = []
                for para in child.findall("Paragraph"):
                    num = txt(para.find("ParagraphNum"))
                    sent = txt(para.find("ParagraphSentence"))
                    parts.append(f"{num} {sent}".strip())
                    for item in para.iter("Item"):
                        parts.append(f"  {txt(item.find('ItemTitle'))} {txt(item.find('ItemSentence'))}")
                    for tag2 in ("Subitem1", "Subitem2", "Subitem3"):
                        for sub in para.iter(tag2):
                            parts.append(f"    {txt(sub.find(tag2 + 'Title'))} {txt(sub.find(tag2 + 'Sentence'))}")
                text = _clean("\n".join(_dedupe_subitems(parts)))
                num_attr = child.get("Num", "").replace("_", "-")
                recs.append(Record(
                    id=f"{meta['doc_id']}-art{num_attr}", country="JP", doc_id=meta["doc_id"],
                    doc_code=meta["doc_code"], title=meta["title"], version=meta["version"],
                    source_url=meta["source_url"], path=path_titles, article_no=art_no, caption=caption,
                    caption_ko=CAPTIONS_KO.get(f"JP:{caption}", ""), text=text, lang="ja",
                ))
            else:
                walk(child, path_titles)

    walk(law_body, [])
    return recs


def _dedupe_subitems(parts: list[str]) -> list[str]:
    # Item.iter()가 하위 Subitem의 문장까지 포함하므로 같은 문장이 두 번 들어가지 않게 정리
    seen, out = set(), []
    for p in parts:
        key = p.strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ---------------------------------------------------------------- 미국: eCFR PDF
_US_NOISE = [
    re.compile(r"^21 CFR (Part )?\d+.*\((up to date as of|Nov\.|enhanced display).*"),
    re.compile(r"^21 CFR \d+(\.\d+)?(\([a-z0-9]+\))*\s*(\(enhanced display\))?\s*(page \d+ of \d+)?$"),
    re.compile(r"^page \d+ of \d+$"),
    re.compile(r"^Current Good Manufacturing Practice .*$"),
    re.compile(r"^This content is from the eCFR.*"),
    re.compile(r"^21 CFR \d+$"),
]


def parse_us_pdf(path: Path, meta: dict) -> list[Record]:
    lines = [(p, ln) for p, ln in _pdf_lines(path) if not any(rx.match(ln) for rx in _US_NOISE)]
    part = meta["part"]
    sec_re = re.compile(rf"^§ ({part}\.\d+[a-z]?)\s+(.+)$")
    sub_re = re.compile(r"^Subpart ([A-Z])\s*[—-]\s*(.+)$")

    # 본문 시작 = 'PART 211—' 제목줄 (그 앞은 목차)
    start = next(i for i, (_, ln) in enumerate(lines) if re.match(rf"^PART {part}\s*[—-]", ln))
    recs: list[Record] = []
    subpart = ""
    cur: dict | None = None

    def flush():
        if not cur:
            return
        text = _join_english(cur["lines"])
        # 개정 이력 각주 [43 FR 45077, Sept. 29, 1978, as amended at …] 는 여러 줄에 걸쳐 있으므로 합친 뒤 제거
        text = _clean(re.sub(r"\s*\[\d+ FR [^\]]*\]", "", text))
        sec = cur["sec"]
        recs.append(Record(
            id=f"{meta['doc_id']}-{sec}", country="US", doc_id=meta["doc_id"], doc_code=meta["doc_code"],
            title=meta["title"], version=meta["version"],
            source_url=f"https://www.ecfr.gov/current/title-21/section-{sec}",
            path=[f"Subpart {subpart}"] if subpart else [], article_no=f"§ {sec}", caption=cur["caption"],
            caption_ko=CAPTIONS_KO.get(f"US:{sec}", ""), text=text or "(본문 없음 — 유보 조항)", lang="en",
            page=cur["page"],
        ))

    for pno, ln in lines[start:]:
        m_sub = sub_re.match(ln)
        m_sec = sec_re.match(ln)
        if m_sub:
            flush(); cur = None
            subpart = f"{m_sub.group(1)} {m_sub.group(2).strip()}"
        elif m_sec:
            flush()
            cap = m_sec.group(2).strip()
            cur = {"sec": m_sec.group(1), "caption": cap.rstrip(". "), "lines": [], "page": pno,
                   "cap_open": not cap.endswith(".")}
        elif cur and cur.get("cap_open"):
            # 제목이 두 줄에 걸친 경우 (예: § 211.84 … containers, and / closures.)
            cur["caption"] = f"{cur['caption']} {ln}".rstrip(". ")
            cur["cap_open"] = not ln.endswith(".")
        elif cur and not ln.startswith(("Authority:", "Source:")):
            cur["lines"].append(ln)
    flush()
    return recs


def _join_english(lines: list[str]) -> str:
    item = re.compile(r"^\(([a-z]|\d+|[ivx]+)\)\s")
    out: list[str] = []
    for ln in lines:
        if out and not item.match(ln):
            out[-1] = out[-1] + (" " if not out[-1].endswith("-") else "") + ln
        else:
            out.append(ln)
    return "\n".join(out)


# ---------------------------------------------------------------- 한국: 법제처 별표 PDF
_KR_NOISE = [re.compile(r"^■ .*\[별표.*\]"), re.compile(r"^- ?\d+ ?-$"), re.compile(r"^\d+ ?/ ?\d+$")]
# 1. 개요 / 1.1 목적 / 12.3 세척 밸리데이션 — 줄 전체가 짧은 제목인 경우만
# 대항목은 반드시 '1.' 처럼 마침표가 있어야 한다 (표 안의 '2 바이러스 …' 같은 행 번호를 제목으로 오인하지 않도록)
_KR_HEAD = re.compile(r"^(\d{1,2}(?=\.)|\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\.?\s*([가-힣A-Za-z(].{0,50})$")


def parse_kr_pdf(path: Path, meta: dict) -> list[Record]:
    lines = [(p, ln) for p, ln in _pdf_lines(path) if not any(rx.match(ln) for rx in _KR_NOISE)]
    # 제목(문서명·관련 조문 괄호) 부분 건너뛰기: 첫 번째 '1. ' 제목부터 본문
    start = next((i for i, (_, ln) in enumerate(lines) if re.match(r"^1\.?\s*[가-힣A-Za-z(]", ln)), None)
    if start is None:
        raise ValueError(f"본문 시작('1. …' 제목)을 찾지 못했습니다: {path.name}")
    recs: list[Record] = []
    top = ""
    cur: dict | None = None

    def is_heading(ln: str) -> re.Match | None:
        m = _KR_HEAD.match(ln)
        # 문장(…한다. …하여야 한다)으로 끝나면 제목이 아니다
        cap = m.group(2).strip() if m else ""
        # 문장(…한다. / …참조).)으로 끝나면 제목이 아니다
        if m and not re.search(r"(다|함|것)\.?$|\.$", cap) and len(cap) <= 40:
            return m
        return None

    def flush():
        if not cur:
            return
        text = _clean(_join_korean(cur["lines"]))
        if not text:
            return
        num = cur["num"]
        recs.append(Record(
            id=f"{meta['doc_id']}-{num}", country="KR", doc_id=meta["doc_id"], doc_code=meta["doc_code"],
            title=meta["title"], version=meta["version"], source_url=meta["source_url"],
            path=[top] if top and top != f"{num} {cur['caption']}" else [], article_no=num,
            caption=cur["caption"], caption_ko=cur["caption"], text=text, lang="ko", page=cur["page"],
        ))

    body = lines[start:]
    # 1) 제목 후보를 모두 찾고  2) 번호가 계속 증가하는 가장 긴 순서(LIS)만 진짜 제목으로 인정한다.
    #    표 안의 '1. 동물 …', '2. 바이러스 …' 같은 행 번호나 본문 속 숫자는 이 순서에서 빠진다.
    #    표의 행처럼 보이는 후보는 가중치를 낮춰, 진짜 제목 순서가 우선 선택되게 한다.
    cands = []
    for i, (pno, ln) in enumerate(body):
        m = is_heading(ln)
        if m:
            w = 0.2 if (pno, ln) in TABLE_GAPS else 1.0
            cands.append((i, tuple(int(x) for x in m.group(1).split(".")), m, w))
    best: list[tuple[float, list[int]]] = []
    for j, (_, kj, _, wj) in enumerate(cands):
        prev = [best[i] for i in range(j) if cands[i][1] < kj and kj[0] - cands[i][1][0] <= 1]
        score, seq = max(prev, key=lambda t: t[0], default=(0.0, []))
        best.append((score + wj, seq + [j]))
    chosen = max(best, key=lambda t: t[0], default=(0.0, []))[1]
    accepted = {cands[j][0]: cands[j][2] for j in chosen}

    for idx, (pno, ln) in enumerate(body):
        m = accepted.get(idx)
        if m:
            num, cap = m.group(1), m.group(2).strip()
            flush()
            if "." not in num:  # 대항목(1. 개요)
                top = f"{num}. {cap}"
            cur = {"num": num, "caption": cap, "lines": [], "page": pno}
        elif cur:
            cur["lines"].append(ln)
    flush()
    return recs


def parse_kr_pdf_whole(path: Path, meta: dict) -> list[Record]:
    """목차·서식처럼 제목만 나열된 짧은 문서는 통째로 1개 레코드로 둔다 (예: 별표 18 제조소 총람 구성)."""
    lines = [ln for _, ln in _pdf_lines(path) if not any(rx.match(ln) for rx in _KR_NOISE)]
    return [Record(
        id=f"{meta['doc_id']}-all", country="KR", doc_id=meta["doc_id"], doc_code=meta["doc_code"],
        title=meta["title"], version=meta["version"], source_url=meta["source_url"], path=[],
        article_no="전체", caption=meta["title"], caption_ko=meta["title"], text=_clean("\n".join(lines)), lang="ko",
    )]


PARSERS = {"jp_xml": parse_jp_xml, "us_pdf": parse_us_pdf, "kr_pdf": parse_kr_pdf, "kr_pdf_whole": parse_kr_pdf_whole}


# ---------------------------------------------------------------- 실행
def load_sources() -> list[dict]:
    import yaml

    return yaml.safe_load((RAW / "sources.yaml").read_text(encoding="utf-8"))["sources"]


def check(recs: list[Record]) -> list[str]:
    problems = []
    ids = [r.id for r in recs]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        problems.append(f"중복 ID {len(dup)}개: {sorted(dup)[:5]}")
    for r in recs:
        if len(r.text) < 15:
            problems.append(f"본문이 너무 짧음: {r.id} ({r.text!r})")
        if len(r.text) > 8000:
            problems.append(f"본문이 매우 김(조항 경계 확인 필요): {r.id} {len(r.text)}자")
    return problems


def write_review_xlsx(all_recs: list[Record], path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "조항 레코드"
    cols = ["id", "country", "doc_code", "path", "article_no", "caption", "caption_ko", "topics", "글자수", "text"]
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="234E52")
    for r in all_recs:
        ws.append([r.id, r.country, r.doc_code, " > ".join(r.path), r.article_no, r.caption, r.caption_ko,
                   ", ".join(r.topics), len(r.text), r.text[:32000]])
    for col, w in zip("ABCDEFGHIJ", (26, 8, 18, 40, 12, 30, 24, 24, 8, 100)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=c.column_letter in ("D", "J"))
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="파일을 쓰지 않고 점검 결과만 출력")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    all_recs: list[Record] = []
    for src in load_sources():
        path = RAW / src["file"]
        if not path.exists():
            print(f"[건너뜀] 원문 없음: {src['file']}")
            continue
        recs = PARSERS[src["parser"]](path, src)
        for r in recs:
            r.topics = tag_topics(f"{r.caption} {r.caption_ko} {r.text}")
        problems = check(recs)
        print(f"[{src['doc_id']}] {len(recs)}개 조항" + (f" — 점검 {len(problems)}건" if problems else ""))
        for p in problems[:10]:
            print("   ·", p)
        all_recs += recs
        if not args.check:
            with open(OUT / f"{src['doc_id']}.jsonl", "w", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps({**asdict(r), "header": r.header()}, ensure_ascii=False) + "\n")
    if not args.check and all_recs:
        write_review_xlsx(all_recs, OUT / "_review.xlsx")
        print(f"검토용 엑셀: {OUT / '_review.xlsx'}")


if __name__ == "__main__":
    main()

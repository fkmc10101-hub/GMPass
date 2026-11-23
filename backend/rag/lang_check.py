"""한국어 답변 속에 번역되지 않은 영어·일본어 구절이 남았는지 찾는다.

답변은 한국어로 쓰되 핵심 원어는 괄호 안에 병기하는 것이 규칙이다.
괄호 밖에 영어 단어나 일본어가 그대로 남아 있으면(예: "specification과 기준", "品質部門이") 번역이 덜 된 것으로 본다.
"""

from __future__ import annotations

import re

# 번역하지 않고 그대로 써도 되는 약어·고유 표기 (대소문자 구분 없이 비교)
ALLOWED = {
    "gmp", "cgmp", "kgmp", "gqp", "gdp", "sop", "capa", "qa", "qc", "qp", "pqr", "oos", "oot", "ooe", "alcoa",
    "cfr", "fda", "mfds", "pmda", "pic", "ich", "eu", "ema", "usp", "iso", "ai", "erp", "lims", "mes",
    "part", "subpart", "annex", "chapter", "section", "eudralex", "api", "dmf", "csv", "pqs",
    "audit", "trail", "kr", "us", "jp", "pdf", "xml",
}

_CITATION = re.compile(r"\[\d+\]")
_PAREN = re.compile(r"\([^()]*\)|（[^（）]*）")
_SECTION_NO = re.compile(r"§\s*[\d.]+(\([a-z0-9]+\))*|\d+\s*CFR\s*(Part\s*)?\d+(\.\d+)?", re.I)
_JAPANESE = re.compile(r"[぀-ヿ一-鿿]+")
_ENGLISH_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")


def _strip_allowed_spans(text: str) -> str:
    """괄호 안 원어 병기, 인용 번호, 조항 번호는 검사에서 뺀다 (여러 겹 괄호도 처리)."""
    prev = None
    while prev != text:
        prev = text
        text = _PAREN.sub(" ", text)
    text = _CITATION.sub(" ", text)
    return _SECTION_NO.sub(" ", text)


def find_untranslated(text: str) -> list[str]:
    """괄호 밖에 남은 영어 단어·일본어 구절 목록. 비어 있으면 통과."""
    body = _strip_allowed_spans(text)
    found: list[str] = []
    for m in _JAPANESE.finditer(body):
        found.append(m.group(0))
    for m in _ENGLISH_WORD.finditer(body):
        if m.group(0).lower().strip("-'") not in ALLOWED:
            found.append(m.group(0))
    return found

"""질문 의도 파악: '나라별 차이'를 묻는 질문인지, 어느 나라를 언급했는지, 핵심 주제가 무엇인지.

왜 필요한가 (2026-11-09 발견)
- "출하 승인에 대해 한국과 미국은 어떻게 달라?"를 통합 답변으로 물으면,
  한국어 질문이라 한국 문서가 검색 상위를 차지하고 미국 근거가 빠진다 → LLM이 '근거 부족'으로 답한다.
- 또 검색어에 '한국', '미국', '차이' 같은 말이 섞이면 정작 주제(출하 승인)와의 유사도가 떨어진다.
→ 차이를 묻는 질문은 ① 나라별로 따로 검색하고 ② 검색어에서는 나라·비교 표현을 빼고 주제만 쓴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

COUNTRY_WORDS: dict[str, list[str]] = {
    "KR": ["한국", "우리나라", "국내", "식약처", "kgmp", "대한민국"],
    "US": ["미국", "fda", "cfr", "21 cfr", "cgmp"],
    "JP": ["일본", "pmda", "후생노동성", "gmp省令", "日本"],
    "EU": ["유럽", "eu", "ema", "eudralex"],
    "PICS": ["pic/s", "pics"],
    "ICH": ["ich"],
}

COMPARE_WORDS = ["차이", "비교", "다른 점", "다른점", "다르", "공통점", "같은 점", "vs", "versus", "대비", "각국", "나라별", "국가별"]

# 검색어에서 지울 표현 (주제만 남기기)
_STRIP = [r"비교해\s*(줘|주세요|봐)?", r"정리해\s*(줘|주세요)?", r"에\s*대해(서)?", r"에\s*관해(서)?", r"(의|은|는|이|가|과|와|랑|하고)?\s*(차이점?|비교|다른\s*점|공통점|같은\s*점)(은|을|이|가)?",
          r"어떻게\s*(다르|달라|다른)\S*", r"(뭐|무엇)(가|이)?\s*(다르|달라)\S*", r"알려\s*(줘|주세요)",
          r"\bvs\.?\b", r"그리고", r"및"]


@dataclass
class Intent:
    is_compare: bool
    countries: list[str] = field(default_factory=list)  # 질문에 언급된 나라 (언급 순서)
    topic: str = ""                                       # 검색에 쓸 핵심 주제


def detect(question: str) -> Intent:
    q = question.lower()
    found: list[tuple[int, str]] = []
    for code, words in COUNTRY_WORDS.items():
        pos = [q.find(w) for w in words if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", q)]
        pos = [p for p in pos if p >= 0]
        if pos:
            found.append((min(pos), code))
    countries = [c for _, c in sorted(found)]
    is_compare = any(w in q for w in COMPARE_WORDS) or len(countries) >= 2

    topic = q
    for words in COUNTRY_WORDS.values():
        for w in sorted(words, key=len, reverse=True):
            topic = re.sub(rf"(?<![a-z]){re.escape(w)}(?![a-z])(의|은|는|이|가|과|와|랑|하고|에서)?", " ", topic)
    for pat in _STRIP:
        topic = re.sub(pat, " ", topic)
    topic = re.sub(r"[?？!.,·]+", " ", topic)
    topic = re.sub(r"\s+", " ", topic).strip()
    if len(topic) < 2:
        topic = question
    return Intent(is_compare, countries, topic)

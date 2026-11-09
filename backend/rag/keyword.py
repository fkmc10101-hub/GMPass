"""키워드 검색(BM25) — 의미 검색(임베딩)을 보완한다.

임베딩 검색은 '뜻이 비슷한' 문장을 잘 찾지만, 조항 제목에 그대로 들어 있는 단어
(예: § 211.100 "Written procedures; deviations")를 놓칠 때가 있다.
BM25는 질문 단어가 실제로 들어 있는 조항에 점수를 주므로, 두 결과를 합치면(하이브리드) 서로의 빈틈을 메운다.

토큰화
- 영어·숫자: 단어 단위 (소문자)
- 한글·일본어(가나·한자): 띄어쓰기가 불규칙하므로 '두 글자 묶음(bigram)' 단위
  예) "점검기록" → 점검, 검기, 기록
"""

from __future__ import annotations

import math
import re
from collections import Counter

_LATIN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")
_CJK = re.compile(r"[가-힣ぁ-んァ-ン一-龥]+")
_STOP = {"the", "of", "and", "or", "to", "in", "a", "an", "be", "shall", "for", "by", "is", "are", "with", "as",
         "on", "that", "this", "any", "such", "at", "from", "which", "have", "has"}


def tokenize(text: str) -> list[str]:
    t = text.lower()
    tokens = [w for w in _LATIN.findall(t) if w not in _STOP and len(w) > 1]
    for run in _CJK.findall(t):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens += [run[i : i + 2] for i in range(len(run) - 1)]
    return tokens


class BM25Index:
    def __init__(self, ids: list[str], texts: list[str], metas: list[dict], k1: float = 1.5, b: float = 0.75):
        self.ids, self.metas = ids, metas
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(t)) for t in texts]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avgdl = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def search(self, query: str, countries: list[str], top_k: int) -> list[tuple[str, float]]:
        q = Counter(tokenize(query))
        allowed = set(countries)
        scored: list[tuple[str, float]] = []
        for i, d in enumerate(self.docs):
            if self.metas[i].get("country") not in allowed:
                continue
            s = 0.0
            for w in q:
                tf = d.get(w)
                if not tf:
                    continue
                s += self.idf[w] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avgdl))
            if s > 0:
                scored.append((self.ids[i], s))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]


def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal Rank Fusion: 여러 검색 결과의 '순위'만으로 합친다 (점수 단위가 달라도 됨)."""
    score: dict[str, float] = {}
    for ranking in rankings:
        for r, vid in enumerate(ranking, start=1):
            score[vid] = score.get(vid, 0.0) + 1.0 / (k + r)
    return [vid for vid, _ in sorted(score.items(), key=lambda x: -x[1])]

"""생성된 답변을 사람이 다시 확인해야 하는지 판정한다.

건강동행에서 얻은 교훈: 전체 지표 하나만 보면 개별 항목의 문제를 놓친다.
그래서 GMPass는 판정 사유를 하나로 합치지 않고, 걸린 사유를 모두 목록으로 돌려준다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .embeddings import Embedder, cosine
from .generator import Generation
from .vectorstore import SearchHit

REASONS = {
    "NO_EVIDENCE": "선택한 국가의 문서에서 관련 근거를 찾지 못했습니다.",
    "LOW_RETRIEVAL_SCORE": "가장 관련 있는 근거의 유사도가 기준보다 낮습니다.",
    "NO_CITATION": "답변에 참고자료 인용이 없습니다.",
    "INVALID_CITATION": "답변이 제공되지 않은 참고자료 번호를 인용했습니다.",
    "INSUFFICIENT_CONTEXT": "모델이 근거가 부족하다고 판단했습니다.",
    "LOW_CONSISTENCY": "같은 질문을 반복 생성했을 때 답변이 일관되지 않습니다.",
    "DRY_RUN": "API 키가 없어 답변을 생성하지 않은 테스트 모드입니다.",
}


@dataclass
class Verdict:
    review_required: bool
    reasons: list[str] = field(default_factory=list)
    top_score: float = 0.0
    consistency: float | None = None

    @property
    def messages(self) -> list[str]:
        return [REASONS[r] for r in self.reasons]


def verify(
    gen: Generation,
    hits: list[SearchHit],
    embedder: Embedder,
    min_retrieval_score: float,
    consistency_threshold: float,
) -> Verdict:
    reasons: list[str] = []
    top = max((h.score for h in hits), default=0.0)

    if gen.model == "dry-run":
        reasons.append("DRY_RUN")
    if not hits:
        reasons.append("NO_EVIDENCE")
    elif top < min_retrieval_score:
        reasons.append("LOW_RETRIEVAL_SCORE")
    if hits and not gen.source_refs:
        reasons.append("NO_CITATION")
    if any(r < 1 or r > len(hits) for r in gen.source_refs):
        reasons.append("INVALID_CITATION")
    if gen.insufficient and hits:
        reasons.append("INSUFFICIENT_CONTEXT")

    consistency = None
    if gen.samples:
        base = embedder.embed_query(gen.answer)
        sims = [cosine(base, embedder.embed_query(s)) for s in gen.samples]
        consistency = round(sum(sims) / len(sims), 4)
        # 일관성은 '정답 여부'가 아니라 '추가 검토가 필요하다는 신호'로만 쓴다
        if consistency < consistency_threshold:
            reasons.append("LOW_CONSISTENCY")

    return Verdict(bool(reasons), reasons, round(top, 4), consistency)

"""국가 간 '주제 태그' 사전.

같은 QA 주제를 나라마다 다른 말로 쓰므로(출하 승인 / release / 出荷判定),
주제별로 한·영·일 키워드를 묶어 두고 조항에 태그를 붙인다.

- 비교 모드에서 같은 태그의 조항을 나라별로 확실히 가져오는 데 쓴다.
- 키워드는 '시작값'이다. 실무 기준으로 직접 추가·삭제하는 것이 이 사전의 핵심 가치다.
- 키워드가 제목(caption)이나 본문에 나오면 태그를 붙인다. 너무 흔한 단어는 넣지 않는다.
"""

from __future__ import annotations

import re

TOPICS: dict[str, list[str]] = {
    "품질시스템·경영책임": ["품질경영", "품질시스템", "의약품 품질시스템", "경영진", "quality system", "management review",
                       "医薬品品質システム", "品質リスクマネジメント", "経営"],
    "품질부서·책임자": ["품질(보증)부서", "품질부서", "품질보증부서", "quality control unit", "品質部門", "品質保証責任者"],
    "출하 승인": ["출하 승인", "출하를 승인", "출하 여부", "출하판정", "release", "出荷", "出荷判定"],
    "문서·기록": ["기준서", "기록서", "문서관리", "기록", "records", "documentation", "written procedures", "文書", "記録",
              "手順書"],
    "제조관리": ["제조관리", "제조공정", "공정관리", "production and process controls", "in-process", "製造管理", "工程管理"],
    "시험·품질관리": ["시험성적서", "시험관리", "시험지시", "laboratory controls", "testing", "試験検査", "品質管理"],
    "원자재·공급업체": ["원자재", "원료약품", "공급업체", "수탁자", "components", "containers and closures", "supplier",
                   "原料", "資材", "供給者"],
    "변경관리": ["변경관리", "변경 관리", "change control", "変更の管理"],
    "일탈·기준일탈": ["일탈", "기준일탈", "deviation", "out-of-specification", "逸脱"],
    "불만·회수": ["불만", "회수", "complaint", "recall", "苦情", "回収"],
    "자율점검·감사": ["자율점검", "self-inspection", "audit", "自己点検"],
    "교육훈련": ["교육", "훈련", "training", "personnel qualifications", "教育訓練"],
    "밸리데이션·적격성평가": ["밸리데이션", "적격성평가", "validation", "qualification", "バリデーション", "適格性評価"],
    "안정성": ["안정성", "사용기한", "stability", "expiration dating", "安定性"],
    "보관검체·참조검체": ["보관검체", "참조검체", "reserve samples", "参考品", "保存品"],
    "시설·환경·위생": ["작업소", "환경관리", "위생", "청정", "buildings and facilities", "sanitation", "ventilation",
                   "構造設備", "衛生管理"],
    "설비·교정": ["기계·설비", "설비", "교정", "equipment", "calibration", "設備", "校正"],
    "위탁·수탁": ["위탁", "수탁", "contract", "委託", "受託"],
    "제품품질평가(PQR)": ["제품품질평가", "annual product review", "product quality review", "製品品質の照査"],
    "전산화 시스템·데이터": ["컴퓨터화 시스템", "전산", "데이터", "electronic", "computer", "データ", "コンピュータ"],
}

_COMPILED = {t: [re.compile(re.escape(k), re.IGNORECASE) for k in kws] for t, kws in TOPICS.items()}


def tag_topics(text: str, min_hits: int = 2) -> list[str]:
    """키워드가 min_hits 번 이상 나오는 주제를 태그로 붙인다 (한 번 스치듯 나온 단어는 제외)."""
    tags = []
    for topic, patterns in _COMPILED.items():
        hits = sum(len(p.findall(text)) for p in patterns)
        if hits >= min_hits:
            tags.append(topic)
    return tags

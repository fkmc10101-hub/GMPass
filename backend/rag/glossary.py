"""질문 확장용 GMP 용어 대응표 (한국어 ↔ 영어 ↔ 일본어).

한국어 질문 "일탈은 어떻게 처리하나요?"는 영어 원문의 "deviation", "discrepancy"와
임베딩 공간에서 충분히 가깝지 않을 수 있다. 질문에 아래 한국어 용어가 있으면
같은 뜻의 영어·일본어 용어를 질문 뒤에 덧붙여 검색한다 (LLM 호출 없음, 비용 0원).

- 첫 평가(2026-11-09)에서 놓친 3건(미국 일탈·PQR·공급업체)이 모두 '용어 차이' 때문이어서 추가했다.
- 용어는 실무 기준으로 자유롭게 추가하면 된다. 너무 넓은 단어(예: '관리')는 넣지 않는다.
"""

from __future__ import annotations

GLOSSARY: dict[str, list[str]] = {
    "일탈": ["deviation", "unexplained discrepancy", "逸脱"],
    "기준일탈": ["out-of-specification", "OOS", "規格外"],
    "제품품질평가": ["annual product review", "evaluating at least annually the quality standards", "製品品質の照査"],
    "PQR": ["annual product review", "product quality review", "製品品質の照査"],
    "공급업체": ["supplier", "vendor", "供給者"],
    "공급자": ["supplier", "供給者"],
    "원료": ["components", "raw materials", "原料"],
    "출하 승인": ["release", "approve or reject", "出荷判定", "出荷の可否"],
    "출하승인": ["release", "approve or reject", "出荷判定"],
    "변경관리": ["change control", "変更の管理"],
    "자율점검": ["self-inspection", "自己点検"],
    "교육훈련": ["training", "教育訓練"],
    "교육": ["training", "教育訓練"],
    "보관검체": ["reserve samples", "参考品", "保存品"],
    "안정성": ["stability testing", "安定性"],
    "불만": ["complaint", "苦情"],
    "회수": ["recall", "回収"],
    "밸리데이션": ["validation", "バリデーション"],
    "세척": ["cleaning", "洗浄"],
    "점검기록": ["audit trail"],
    "audit trail": ["점검기록", "AuditTrail", "監査証跡"],
    "전산": ["computer", "electronic records", "コンピュータ"],
    "제조기록": ["batch production record", "製造記録"],
    "제조 기록": ["batch production record", "製造記録"],
    # 보관 기간: '얼마나 보관해야 해?'가 211.180(a) '1 year after the expiration date'를 못 찾던 문제 (2026-11-09)
    "보관해야": ["record retention", "retained for at least 1 year after the expiration date", "保存しなければならない"],
    "보관 기간": ["record retention", "retained for at least 1 year after the expiration date", "保存期間"],
    "보관기간": ["record retention", "retained for at least 1 year after the expiration date", "保存期間"],
    "품질부서": ["quality control unit", "品質部門"],
    "위탁": ["contract", "委託"],
}


def expand_query(question: str, max_terms: int = 8) -> str:
    """질문에 들어 있는 한국어 GMP 용어의 영어·일본어 대응어를 덧붙인다."""
    extra: list[str] = []
    for ko, terms in GLOSSARY.items():
        if ko.lower() in question.lower():
            for t in terms:
                if t not in extra and t.lower() not in question.lower():
                    extra.append(t)
    if not extra:
        return question
    return f"{question} ({', '.join(extra[:max_terms])})"

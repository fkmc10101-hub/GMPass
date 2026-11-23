"""LLM 답변 생성. 참고자료 번호 인용을 JSON으로 강제한다.

OPENAI_API_KEY 가 없으면 DryRunGenerator가 동작해 검색 결과만으로 응답 틀을 만든다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .countries import JURISDICTIONS
from .lang_check import find_untranslated
from .vectorstore import SearchHit

SYSTEM_PROMPT = """너는 제약 품질보증(QA) 담당자를 돕는 GMP 가이던스 안내 도우미다.
반드시 아래 규칙을 지켜라.
1. 제공된 [참고자료] 안의 내용만 근거로 답한다. 참고자료에 없는 내용은 추측하지 않는다.
2. 문장마다 근거가 된 참고자료 번호를 [1], [2]처럼 표시한다.
3. 참고자료가 질문에 답하기에 부족하면 insufficient를 true로 하고, 무엇이 부족한지 answer에 짧게 쓴다.
4. 답변은 처음부터 끝까지 한국어 문장으로 쓴다. 영어·일본어 구절을 문장 속에 그대로 남기지 않는다.
   - 규정 용어는 한국어로 옮기고, 필요하면 처음 한 번만 괄호로 원어를 병기한다. (예: 품질관리부서(quality control unit), 제조관리자(製造管理者))
   - 괄호 밖에는 영어 단어나 일본어를 쓰지 않는다. 조항 번호는 한국어 표기로 쓰고 원문 표기는 괄호에 둔다. (예: 제5조(第五条), § 211.22)
   - 나열 조항이나 긴 원문 구절도 한국어로 풀어 쓴다.
5. 법적 해석이나 실사 대응 판단을 대신하지 않는다는 점을 전제로, 사실만 간결하게 정리한다.
반드시 다음 JSON 형식으로만 답한다:
{"answer": "...", "source_refs": [1, 2], "insufficient": false}"""


COMPARE_PROMPT = """너는 제약 품질보증(QA) 담당자를 돕는 GMP 가이던스 비교 분석 도우미다.
[참고자료]에는 여러 나라의 조항이 섞여 있고, 각 자료 앞에 (나라)가 표시되어 있다. 반드시 아래 규칙을 지켜라.
1. 각 나라의 내용은 그 나라 참고자료만 근거로 쓴다. 다른 나라 자료로 추측해 채우지 않는다.
2. 문장마다 근거 번호 [1], [2]를 붙인다. 번호 뒤에 조항 제목을 덧붙일 때도 한국어로 쓴다. (예: [5] § 211.165 출하 시험 및 승인)
   영어·일본어 구절을 문장 속에 그대로 남기지 않는다. 규정 용어는 한국어로 옮기고, 필요하면 처음 한 번만 괄호로 원어를 병기한다. (예: 품질관리부서(quality control unit), 일탈 관리(逸脱の管理))
   괄호 밖에는 영어 단어나 일본어를 쓰지 않는다. 조항 번호는 한국어로 쓰고 원문 표기는 괄호에 둔다. (예: 제5조(第五条))
3. answer는 한국어로, 다음 순서로 쓴다. 줄바꿈으로 구분한다.
   ■ 나라별 핵심 요건: 나라마다 1~3문장
   ■ 공통점: 1~3문장
   ■ 차이점: '누가(책임 주체) / 무엇을(요구 범위) / 어떻게(절차·기록·기한)' 관점에서 1~4개 항목
   ■ 실무 시사점: 여러 나라에 동시에 대응할 때 확인할 점 1~2문장 (근거 범위 안에서만)
4. 어떤 나라의 참고자료가 주제와 관련이 없으면 그 나라는 "등록된 근거에서 해당 내용을 찾지 못함"이라고 쓰고, 나머지 나라로 비교한다.
   비교할 근거가 있는 나라가 2개 미만일 때만 insufficient를 true로 한다.
5. 법적 해석이나 실사 대응 판단을 대신하지 않는다.
반드시 다음 JSON 형식으로만 답한다:
{"answer": "...", "source_refs": [1, 2], "insufficient": false}"""


@dataclass
class Generation:
    answer: str
    source_refs: list[int]
    insufficient: bool
    model: str
    raw: str = ""
    samples: list[str] = field(default_factory=list)  # self-consistency용 추가 답변


def format_context(hits: list[SearchHit]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        m = h.metadata
        country = JURISDICTIONS.get(m.get("country", ""), None)
        label = country.name_ko if country else m.get("country", "")
        head = f"[{i}] ({label}) {m.get('doc_code') or m.get('title', '')}"
        if m.get("version"):
            head += f" {m['version']}"
        if m.get("section"):
            head += f" / {m['section']}"
        if m.get("page", -1) not in ("", -1, None):
            head += f" / p.{m['page']}"
        blocks.append(f"{head}\n{h.text}")
    return "\n\n".join(blocks)


def parse_generation(raw: str, model: str) -> Generation:
    """모델 응답 JSON을 관대하게 파싱한다 (인용 형식이 응답마다 조금씩 달라질 수 있음)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {"answer": raw, "source_refs": [], "insufficient": True}
    refs = data.get("source_refs", [])
    if isinstance(refs, (int, str)):
        refs = [refs]
    parsed: list[int] = []
    for r in refs or []:
        try:
            parsed.append(int(str(r).strip("[] ")))
        except ValueError:
            continue
    answer = str(data.get("answer", "")).strip()
    # source_refs가 비어 있어도 본문에 [n] 표시가 있으면 함께 인정
    for n in re.findall(r"\[(\d+)\]", answer):
        if int(n) not in parsed:
            parsed.append(int(n))
    return Generation(answer, sorted(set(parsed)), bool(data.get("insufficient", False)), model, raw)


class OpenAIGenerator:
    def __init__(self, api_key: str, model: str, temperature: float = 0.0):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature

    def _create(self, **kwargs):
        """추론형 모델(GPT-5 계열 등)은 temperature 지정을 거부할 수 있다 → 한 번 실패하면 이후엔 빼고 호출."""
        if getattr(self, "_no_temperature", False):
            kwargs.pop("temperature", None)
        try:
            return self._client.chat.completions.create(model=self.model, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if "temperature" in str(exc).lower() and "temperature" in kwargs:
                self._no_temperature = True
                kwargs.pop("temperature")
                return self._client.chat.completions.create(model=self.model, **kwargs)
            raise

    def _call(self, question: str, context: str, temperature: float, system: str = SYSTEM_PROMPT) -> str:
        resp = self._create(
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"[참고자료]\n{context}\n\n[질문]\n{question}"},
            ],
        )
        return resp.choices[0].message.content or "{}"

    def translate(self, text: str) -> str:
        resp = self._create(
            temperature=0,
            messages=[{"role": "system", "content": TRANSLATE_PROMPT}, {"role": "user", "content": text}],
        )
        return (resp.choices[0].message.content or "").strip()

    def _enforce_korean(self, gen: Generation, question: str, context: str, system: str, tries: int = 3) -> Generation:
        """괄호 밖에 영어·일본어가 남은 답변은 해당 구절을 알려 주고 다시 쓰게 한다. 가장 깨끗한 답변을 남긴다."""
        best = gen
        for _ in range(tries):
            bad = find_untranslated(best.answer)
            if not bad:
                break
            fragments = ", ".join(dict.fromkeys(bad))
            retry_question = (
                f"{question}\n\n[수정 지시] 직전 답변에 번역되지 않은 구절이 남아 있었다: {fragments}\n"
                "이 구절을 모두 한국어로 옮겨 처음부터 다시 답하라. 원어는 괄호 안에만 병기하고, 근거 번호 [n]은 그대로 유지한다."
            )
            retry = parse_generation(self._call(retry_question, context, self.temperature, system), self.model)
            if len(find_untranslated(retry.answer)) < len(bad):
                best = retry
        return best

    def compare(self, question: str, hits: list[SearchHit]) -> Generation:
        """여러 나라 근거를 한 번에 보고 공통점·차이점을 정리한다."""
        context = format_context(hits)
        gen = parse_generation(self._call(question, context, self.temperature, COMPARE_PROMPT), self.model)
        return self._enforce_korean(gen, question, context, COMPARE_PROMPT)

    def generate(self, question: str, hits: list[SearchHit], n_samples: int = 1) -> Generation:
        context = format_context(hits)
        gen = parse_generation(self._call(question, context, self.temperature), self.model)
        gen = self._enforce_korean(gen, question, context, SYSTEM_PROMPT)
        # 같은 질문을 여러 번 생성해 답변이 흔들리는지 확인 (self-consistency)
        for _ in range(max(0, n_samples - 1)):
            extra = parse_generation(self._call(question, context, 0.7), self.model)
            gen.samples.append(extra.answer)
        return gen


TRANSLATE_PROMPT = """너는 제약 GMP 규정 번역가다. 주어진 원문을 한국어로 정확히 번역한다.
- 국내 KGMP 실무 용어를 쓴다 (예: quality control unit → 품질관리부서, batch → 제조단위, 出荷判定 → 출하 판정).
- 조항 번호(§ 211.22, 第十二条, (a)(1) 등)와 핵심 원어는 괄호로 병기한다.
- 원문에 없는 내용을 덧붙이거나 요약하지 않는다. 번역문만 출력한다."""


class DryRunGenerator:
    """API 키 없이 파이프라인을 확인하기 위한 생성기. 검색된 근거를 그대로 요약 형식으로 돌려준다."""

    model = "dry-run"

    def translate(self, text: str) -> str:
        raise RuntimeError("번역은 OPENAI_API_KEY가 있어야 사용할 수 있습니다.")

    def compare(self, question: str, hits: list[SearchHit]) -> Generation:
        return self.generate(question, hits)

    def generate(self, question: str, hits: list[SearchHit], n_samples: int = 1) -> Generation:
        if not hits:
            return Generation("관련 근거를 찾지 못했습니다.", [], True, self.model)
        lines = [f"[dry-run] OPENAI_API_KEY가 없어 답변을 생성하지 않았습니다. 검색된 근거 {len(hits)}건:"]
        for i, h in enumerate(hits, start=1):
            lines.append(f"[{i}] {h.text[:120]}…")
        return Generation("\n".join(lines), list(range(1, len(hits) + 1)), False, self.model)

"""체험용 데모(GitHub Pages)에 쓸 답변 스냅샷을 만든다.

실행 중인 백엔드(http://localhost:8000)에 대표 질문을 실제로 물어보고,
답변·근거·번역·문서 목록을 frontend/public/demo/snapshot.json 하나로 저장한다.
데모 페이지는 이 파일만 읽으므로 서버·OpenAI 키 없이 동작하고 요금도 나가지 않는다.

사용법 (backend 폴더, 가상환경 켠 상태, 백엔드 서버가 다른 터미널에서 실행 중일 때)
    python -m scripts.export_demo
    python -m scripts.export_demo --base http://localhost:8000 --chunks 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

# 인사팀·면접관이 눌러 볼 대표 질문 (나라 간 비교 질문은 자동으로 비교 모드로 전환됨)
DEMO_QUESTIONS: list[dict] = [
    {"q": "출하 승인에 대해 한국과 미국은 어떻게 달라?", "group": "나라별 차이"},
    {"q": "일탈 처리 한국 미국 일본 비교해줘", "group": "나라별 차이"},
    {"q": "자율점검(자체점검) 요구사항을 한국과 일본 비교해줘", "group": "나라별 차이"},
    {"q": "전산 시스템의 Audit Trail 요구사항은?", "group": "실무 질문"},
    {"q": "완제품 출하 승인은 누가 하나요?", "group": "실무 질문"},
    {"q": "변경관리 절차에서 꼭 평가해야 할 항목은?", "group": "실무 질문"},
    {"q": "제품품질평가(연차 품질 평가)는 얼마나 자주 해야 해?", "group": "실무 질문"},
    {"q": "원료 공급업체는 어떻게 관리해야 해?", "group": "실무 질문"},
    {"q": "미국 cGMP에서 제조 기록은 얼마나 보관해야 해?", "group": "나라별 규정"},
    {"q": "일본 GMP 성령에서 제조관리자의 역할은?", "group": "나라별 규정"},
    {"q": "무균의약품 작업소 청정도 등급 기준은?", "group": "나라별 규정"},
    {"q": "공정 밸리데이션은 언제, 어떻게 해야 해?", "group": "나라별 규정"},
]
COUNTRIES = ["KR", "US", "JP"]

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "public" / "demo" / "snapshot.json"


def call(base: str, path: str, body: dict | None = None, timeout: int = 300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--chunks", type=int, default=20, help="문서 미리보기에 넣을 문서당 청크 수")
    ap.add_argument("--no-translate", action="store_true", help="영어·일본어 근거 번역을 미리 만들지 않음")
    ap.add_argument("--only", default="", help="이 글자가 들어간 질문만 다시 만들어 기존 스냅샷에 덮어씀 (예: --only cGMP)")
    args = ap.parse_args()

    try:
        health = call(args.base, "/api/health")
    except urllib.error.URLError:
        print(f"백엔드({args.base})에 연결할 수 없습니다. 다른 터미널에서 uvicorn을 먼저 실행하세요.")
        return 1
    if health["dry_run"]:
        print("지금 백엔드가 테스트 모드(dry-run)입니다. backend/.env에 OPENAI_API_KEY를 넣고 다시 실행하세요.")
        return 1

    previous = json.loads(OUT.read_text(encoding="utf-8")) if args.only and OUT.exists() else None
    snapshot: dict = {
        "generated_at": date.today().isoformat(),
        "health": health,
        "countries": call(args.base, "/api/countries"),
        "questions": [],
        "answers": {},
        "translations": {},
        "documents": [],
        "chunks": {},
    }

    if previous:
        snapshot["answers"].update(previous.get("answers", {}))
        snapshot["translations"].update(previous.get("translations", {}))
    snapshot["questions"] = list(DEMO_QUESTIONS)

    for i, item in enumerate(DEMO_QUESTIONS, 1):
        if args.only and (args.only not in item["q"] and item["q"] in snapshot["answers"]):
            continue  # 이번에 다시 만들 대상이 아니면 기존 답변 유지
        started = time.time()
        res = call(args.base, "/api/chat/ask",
                   {"question": item["q"], "countries": COUNTRIES, "mode": "single", "use_cache": False})
        snapshot["answers"][item["q"]] = res
        flagged = sum(a["review_required"] for a in res["answers"])
        print(f"[{i:2}/{len(DEMO_QUESTIONS)}] {item['q']} → {res['mode']}, 카드 {len(res['answers'])}개, "
              f"검토 필요 {flagged}개, {time.time() - started:.0f}초")

        if args.no_translate:
            continue
        for a in res["answers"]:
            for c in a["citations"]:
                cid = c.get("chunk_id")
                if c["cited"] and cid and c["country"] != "KR" and str(cid) not in snapshot["translations"]:
                    try:
                        snapshot["translations"][str(cid)] = call(args.base, "/api/translate", {"chunk_id": cid})
                    except urllib.error.HTTPError as exc:
                        print(f"     번역 실패 chunk {cid}: {exc}")

    snapshot["documents"] = call(args.base, "/api/documents")
    for d in snapshot["documents"]:
        snapshot["chunks"][str(d["id"])] = call(args.base, f"/api/documents/{d['id']}/chunks?limit={args.chunks}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    kb = OUT.stat().st_size // 1024
    print(f"\n저장 완료: {OUT} ({kb} KB) · 질문 {len(snapshot['questions'])}개 · 번역 {len(snapshot['translations'])}건")
    print("검토 필요 표시가 붙은 답변은 화면에서 확인해 보고, 마음에 들지 않으면 DEMO_QUESTIONS에서 질문을 바꿔 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

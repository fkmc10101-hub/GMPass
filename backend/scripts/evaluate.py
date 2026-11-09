"""검색 정확도 평가 (LLM 호출 없음, 비용 0원).

사용법 (backend 폴더에서, 문서 색인 후):
    python -m scripts.evaluate                 # data/eval/questions.csv 기준 Recall@5
    python -m scripts.evaluate --top-k 3

질문마다 '정답 조항 ID'가 검색 상위 k개 안에 하나라도 들어오면 성공으로 센다.
청킹 방식·임베딩 모델·header 형식을 바꿀 때마다 이 숫자를 비교해 개선 여부를 판단한다.
결과는 data/eval/result_<날짜시각>.csv 로 저장된다.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.main import build_pipeline  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--file", default=str(ROOT / "data" / "eval" / "questions.csv"))
    args = ap.parse_args()

    pipeline = build_pipeline(get_settings())
    rows = list(csv.DictReader(open(args.file, encoding="utf-8-sig")))
    results, by_country = [], defaultdict(lambda: [0, 0])
    for row in rows:
        expected = {x.strip() for x in row["expected_ids"].split(";") if x.strip()}
        hits = pipeline.search(row["question"], [row["country"]], args.top_k)
        got = [h.metadata.get("record_id", "") for h in hits]
        rank = next((i + 1 for i, rid in enumerate(got) if rid in expected), None)
        by_country[row["country"]][0] += rank is not None
        by_country[row["country"]][1] += 1
        results.append({**row, "hit": rank is not None, "rank": rank or "", "top_ids": ";".join(got)})
        print(f"{'O' if rank else 'X'} [{row['country']}] {row['question']}  → {rank or '-'}위")

    total_hit = sum(v[0] for v in by_country.values())
    print(f"\nRecall@{args.top_k}: {total_hit}/{len(rows)} = {total_hit / max(1, len(rows)):.0%}")
    for c, (h, n) in sorted(by_country.items()):
        print(f"  {c}: {h}/{n}")
    out = ROOT / "data" / "eval" / f"result_{datetime.now():%Y%m%d_%H%M}.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"결과 저장: {out}")


if __name__ == "__main__":
    main()

"""단계별 소요 시간 기록 + (선택) Langfuse 전송.

건강동행에서 얻은 교훈 두 가지를 반영했다.
1. 전체 응답 시간만으로는 어디가 느린지 알 수 없다 → 검색·생성·검증 단계별 시간을 항상 응답에 포함한다.
2. 추적 코드가 조용히 실패하면 '기록이 없다'는 오해가 생긴다 → 실패 시 반드시 경고 로그를 남긴다.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import contextmanager

log = logging.getLogger("gmpass.tracing")


class Trace:
    def __init__(self, name: str, metadata: dict | None = None):
        self.id = uuid.uuid4().hex
        self.name = name
        self.metadata = metadata or {}
        self.timings_ms: dict[str, int] = {}
        self.spans: list[dict] = []

    @contextmanager
    def span(self, name: str, **attrs):
        start = time.perf_counter()
        record = {"name": name, **attrs}
        try:
            yield record
        finally:
            elapsed = int((time.perf_counter() - start) * 1000)
            self.timings_ms[name] = self.timings_ms.get(name, 0) + elapsed
            record["ms"] = elapsed
            self.spans.append(record)

    def flush(self) -> None:
        """Langfuse 키가 있으면 전송. 실패해도 서비스 응답에는 영향을 주지 않되, 로그는 남긴다."""
        if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
            return
        try:
            from langfuse import get_client

            lf = get_client()
            # SDK v5: start_as_current_observation / v3~4: start_as_current_span
            start = getattr(lf, "start_as_current_observation", None) or lf.start_as_current_span
            with start(name=self.name, metadata={**self.metadata, "trace_id": self.id}) as root:
                for s in self.spans:
                    with start(name=s["name"], metadata=s):
                        pass
                root.update(output={"timings_ms": self.timings_ms})
            lf.flush()
        except Exception as exc:  # noqa: BLE001
            log.warning("Langfuse 전송 실패(trace_id=%s): %s", self.id, exc)

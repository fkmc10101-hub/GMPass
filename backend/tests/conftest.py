"""테스트 공통 설정.

- 임베딩: HashingEmbedder (모델 다운로드 없음)
- 벡터DB: 메모리 Chroma
- 생성기: FakeGenerator (OpenAI 호출 없음, 비용 0원)
- 테스트 문서: tests/fixtures 의 '테스트용 가상 문서' (실제 규정 원문 아님)
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from rag.embeddings import HashingEmbedder  # noqa: E402
from rag.generator import Generation  # noqa: E402
from rag.pipeline import RagPipeline, RagSettings  # noqa: E402
from rag.vectorstore import VectorStore  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


class FakeGenerator:
    """첫 번째 근거를 인용하는 고정 답변. calls로 호출 횟수를 센다(캐시 테스트용)."""

    model = "fake-llm"

    def __init__(self):
        self.calls = 0
        self.mode = "ok"  # ok / no_cite / unstable

    def translate(self, text):
        self.translations = getattr(self, "translations", 0) + 1
        return f"[번역] {text[:20]}"

    def compare(self, question, hits):
        self.compares = getattr(self, "compares", 0) + 1
        countries = sorted({h.metadata["country"] for h in hits})
        return Generation(f"비교: {','.join(countries)} [1]", [1], False, self.model)

    def generate(self, question, hits, n_samples=1):
        self.calls += 1
        if not hits:
            return Generation("근거가 없습니다.", [], True, self.model)
        if self.mode == "no_cite":
            return Generation("근거 표시 없이 쓴 답변입니다.", [], False, self.model)
        gen = Generation(f"{hits[0].metadata['country']} 기준 요약입니다 [1].", [1], False, self.model)
        if self.mode == "unstable":
            gen.samples = ["완전히 다른 내용 apple banana", "xyz 무관한 문장 12345"]
        else:
            gen.samples = [gen.answer] * (n_samples - 1)
        return gen


@pytest.fixture
def fake_generator():
    return FakeGenerator()


@pytest.fixture
def pipeline(fake_generator):
    return RagPipeline(
        VectorStore(None), HashingEmbedder(), fake_generator,
        RagSettings(top_k=3, chunk_max_chars=400, chunk_overlap_chars=50, min_retrieval_score=0.05),
    )


@pytest.fixture
def client(tmp_path, pipeline):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path/'test.db'}",
        chroma_dir=None,
        upload_dir=str(tmp_path / "raw"),
        embedding_backend="hash",
        openai_api_key="",
        admin_token="",
    )
    app = create_app(settings, pipeline)
    with TestClient(app) as c:
        yield c


def upload(client, fixture_name, country, title, **extra):
    path = FIXTURES / fixture_name
    with open(path, "rb") as f:
        return client.post(
            "/api/documents",
            files={"file": (fixture_name, f, "text/plain")},
            data={"country": country, "title": title, **extra},
        )

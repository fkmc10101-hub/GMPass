"""임베딩(문장 → 벡터) 모듈.

- SentenceTransformerEmbedder: 실제 서비스용. API 비용 없이 로컬에서 실행.
  기본 모델 intfloat/multilingual-e5-small 은 한국어·영어·일본어 문서를 한 공간에서 검색할 수 있다.
  (더 높은 품질이 필요하면 EMBEDDING_MODEL=BAAI/bge-m3, 단 메모리를 더 많이 쓴다)
- HashingEmbedder: 모델 다운로드 없이 동작하는 테스트·오프라인용. 의미 검색 품질은 낮다.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class HashingEmbedder:
    """문자 n-gram을 해시해 고정 길이 벡터로 만든다 (결정적·무료·오프라인)."""

    def __init__(self, dim: int = 512, ngram: int = 3):
        self.dim = dim
        self.ngram = ngram
        self.name = f"hash-{dim}"

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        t = re.sub(r"\s+", " ", text.lower())
        tokens = re.findall(r"[a-z0-9]+|[가-힣]+|[ぁ-んァ-ン一-龥]+", t)
        grams: list[str] = list(tokens)
        for tok in tokens:
            grams += [tok[i : i + self.ngram] for i in range(max(1, len(tok) - self.ngram + 1))]
        for g in grams:
            h = int(hashlib.md5(g.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0 if (h >> 8) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # 무거운 import는 사용할 때만

        self.name = model_name
        self._model = SentenceTransformer(model_name)
        # e5 계열은 질의/문서 앞에 접두어를 붙여야 성능이 나온다
        self._is_e5 = "e5" in model_name.lower()

    def _prefix(self, texts: list[str], kind: str) -> list[str]:
        return [f"{kind}: {t}" for t in texts] if self._is_e5 else texts

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(self._prefix(texts, "passage"), normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vecs]

    def embed_query(self, text: str) -> list[float]:
        return self._model.encode(self._prefix([text], "query"), normalize_embeddings=True)[0].tolist()


def build_embedder(backend: str, model_name: str) -> Embedder:
    if backend == "hash":
        return HashingEmbedder()
    if backend == "sentence_transformers":
        return SentenceTransformerEmbedder(model_name)
    raise ValueError(f"알 수 없는 EMBEDDING_BACKEND: {backend}")

"""ChromaDB 래퍼. 청크 벡터와 메타데이터(국가·문서·조항·페이지)를 저장한다."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import chromadb

COLLECTION = "gmp_guidance"


@dataclass
class SearchHit:
    vector_id: str
    text: str
    score: float  # 코사인 유사도 (1에 가까울수록 유사)
    metadata: dict


class VectorStore:
    def __init__(self, persist_dir: str | None):
        # persist_dir 이 None 이면 메모리에서만 동작 (테스트용)
        if persist_dir:
            self._client = chromadb.PersistentClient(path=persist_dir)
            name = COLLECTION
        else:
            # 메모리 클라이언트는 프로세스 안에서 공유되므로 인스턴스마다 컬렉션 이름을 달리한다
            self._client = chromadb.EphemeralClient()
            name = f"{COLLECTION}-{uuid.uuid4().hex[:8]}"
        self._col = self._client.get_or_create_collection(
            name, metadata={"hnsw:space": "cosine"}, embedding_function=None
        )

    @staticmethod
    def vector_id(document_id: int, chunk_index: int) -> str:
        return f"doc{document_id}-c{chunk_index}"

    def add(self, ids: list[str], embeddings: list[list[float]], texts: list[str], metadatas: list[dict]) -> None:
        # Chroma 메타데이터는 None을 허용하지 않으므로 빈 문자열/‑1로 바꾼다
        clean = [{k: ("" if v is None else v) for k, v in m.items()} for m in metadatas]
        for i in range(0, len(ids), 500):
            self._col.add(
                ids=ids[i : i + 500],
                embeddings=embeddings[i : i + 500],
                documents=texts[i : i + 500],
                metadatas=clean[i : i + 500],
            )

    def delete_document(self, document_id: int) -> None:
        self._col.delete(where={"document_id": document_id})

    def count(self) -> int:
        return self._col.count()

    def all_documents(self) -> tuple[list[str], list[str], list[dict]]:
        """키워드(BM25) 색인을 만들 때 쓰는 전체 청크 목록."""
        res = self._col.get(include=["documents", "metadatas"])
        return res["ids"], res["documents"], [dict(m) for m in res["metadatas"]]

    def get_with_scores(self, ids: list[str], query_embedding: list[float]) -> list[SearchHit]:
        """키워드 검색으로만 찾은 청크도 질문과의 의미 유사도(score)를 계산해 돌려준다 (검토 판정 기준을 통일하기 위해)."""
        if not ids:
            return []
        res = self._col.get(ids=ids, include=["documents", "metadatas", "embeddings"])
        by_id = {}
        for vid, doc, meta, emb in zip(res["ids"], res["documents"], res["metadatas"], res["embeddings"]):
            dot = sum(a * b for a, b in zip(query_embedding, emb))
            na = sum(a * a for a in query_embedding) ** 0.5
            nb = sum(b * b for b in emb) ** 0.5
            by_id[vid] = SearchHit(vid, doc, round(dot / (na * nb), 4) if na and nb else 0.0, dict(meta))
        return [by_id[i] for i in ids if i in by_id]

    def search(self, query_embedding: list[float], countries: list[str], top_k: int) -> list[SearchHit]:
        if self._col.count() == 0:
            return []
        where = {"country": countries[0]} if len(countries) == 1 else {"country": {"$in": countries}}
        res = self._col.query(query_embeddings=[query_embedding], n_results=min(top_k, self._col.count()), where=where)
        hits: list[SearchHit] = []
        for vid, doc, dist, meta in zip(res["ids"][0], res["documents"][0], res["distances"][0], res["metadatas"][0]):
            hits.append(SearchHit(vid, doc, round(1.0 - float(dist), 4), dict(meta)))
        return hits

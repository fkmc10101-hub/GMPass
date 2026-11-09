"""GMPass API 서버 진입점.

실행: (backend 폴더에서) uvicorn app.main:app --reload
문서: http://localhost:8000/docs
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rag.embeddings import build_embedder
from rag.pipeline import RagPipeline, RagSettings, build_generator
from rag.vectorstore import VectorStore

from .config import Settings, get_settings
from .database import Base, make_engine, make_session_factory
from .routers import chat, documents, meta, translate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_pipeline(settings: Settings) -> RagPipeline:
    return RagPipeline(
        store=VectorStore(settings.chroma_dir or None),
        embedder=build_embedder(settings.embedding_backend, settings.embedding_model),
        generator=build_generator(settings.openai_api_key, settings.llm_model, settings.llm_temperature),
        settings=RagSettings(
            top_k=settings.top_k,
            chunk_max_chars=settings.chunk_max_chars,
            chunk_overlap_chars=settings.chunk_overlap_chars,
            min_retrieval_score=settings.min_retrieval_score,
            self_consistency_n=settings.self_consistency_n,
            self_consistency_threshold=settings.self_consistency_threshold,
            query_expansion=settings.query_expansion,
            hybrid_search=settings.hybrid_search,
        ),
    )


def create_app(settings: Settings | None = None, pipeline: RagPipeline | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Langfuse SDK는 환경변수를 직접 읽으므로 .env 값을 넘겨 준다
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
        os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        Base.metadata.create_all(engine)  # 개인 프로젝트 규모라 마이그레이션 도구 없이 시작
        app.state.settings = settings
        app.state.session_factory = make_session_factory(engine)
        app.state.pipeline = pipeline or build_pipeline(settings)
        yield
        engine.dispose()

    app = FastAPI(
        title="GMPass API",
        description="국가별 GMP 가이던스를 근거와 함께 찾아 주는 RAG 챗봇",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(meta.router)
    app.include_router(chat.router)
    app.include_router(documents.router)
    app.include_router(translate.router)
    return app


app = create_app()

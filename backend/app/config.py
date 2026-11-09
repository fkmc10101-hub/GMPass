from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0

    embedding_backend: str = "sentence_transformers"  # 또는 hash
    embedding_model: str = "intfloat/multilingual-e5-small"

    database_url: str = "sqlite:///./gmpass.db"
    chroma_dir: str | None = "../data/chroma"  # 빈 값이면 메모리(테스트)
    upload_dir: str = "../data/raw"

    top_k: int = 5
    chunk_max_chars: int = 1000
    chunk_overlap_chars: int = 150
    min_retrieval_score: float = 0.35
    self_consistency_n: int = 3
    self_consistency_threshold: float = 0.75
    cache_ttl_days: int = 7
    query_expansion: bool = True
    hybrid_search: bool = True
    max_upload_mb: int = 50

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    admin_token: str = ""
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()

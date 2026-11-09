from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CountryOut(BaseModel):
    code: str
    name_ko: str
    authority: str
    main_documents: list[str]
    language: str
    indexed_documents: int


# ---------- 채팅 ----------
class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    countries: list[str] = Field(default_factory=list, description="비우면 전체 국가")
    mode: Literal["single", "compare"] = "single"
    session_id: int | None = None
    use_cache: bool = True


class CitationOut(BaseModel):
    ref_no: int
    cited: bool
    chunk_id: int | None
    document_id: int | None
    country: str
    document_title: str
    doc_code: str
    version: str
    effective_date: str
    section: str
    page: int | None
    source_url: str
    score: float
    snippet: str


class AnswerOut(BaseModel):
    message_id: int | None = None
    country: str
    answer: str
    citations: list[CitationOut]
    review_required: bool
    review_reasons: list[str]
    review_messages: list[str]
    top_score: float
    consistency: float | None


class AskResponse(BaseModel):
    session_id: int
    question_message_id: int
    mode: str
    countries: list[str]
    answers: list[AnswerOut]
    model: str
    cached: bool
    latency_ms: int
    timings_ms: dict[str, int]
    trace_id: str


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    created_at: datetime
    message_count: int = 0


class MessageOut(BaseModel):
    id: int
    role: str
    country: str
    content: str
    countries: list[str]
    mode: str
    review_required: bool
    review_reasons: list[str]
    citations: list[CitationOut]
    created_at: datetime


class SessionDetailOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    messages: list[MessageOut]


class FeedbackIn(BaseModel):
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=1000)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    message_id: int
    rating: str
    comment: str
    created_at: datetime


# ---------- 문서 ----------
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    country: str
    title: str
    doc_code: str
    version: str
    effective_date: str
    language: str
    source_url: str
    file_name: str
    status: str
    chunk_count: int
    error_message: str
    created_at: datetime
    updated_at: datetime


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    chunk_index: int
    section: str
    page: int | None
    char_count: int
    text: str


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    countries: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchHitOut(BaseModel):
    vector_id: str
    country: str
    document_id: int
    document_title: str
    section: str
    page: int | None
    score: float
    text: str


class HealthOut(BaseModel):
    status: str
    dry_run: bool
    llm_model: str
    embedding_model: str
    indexed_chunks: int


class TranslateIn(BaseModel):
    chunk_id: int


class TranslateOut(BaseModel):
    chunk_id: int
    source_language: str
    original: str
    text_ko: str
    model: str
    cached: bool
    notice: str = "기계 번역입니다. 판단 근거는 원문을 기준으로 하세요."

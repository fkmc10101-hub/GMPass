"""DB 테이블 정의. docs/GMPass_ERD.dbml 과 같은 구조다."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country: Mapped[str] = mapped_column(String(8), index=True)
    title: Mapped[str] = mapped_column(String(300))
    doc_code: Mapped[str] = mapped_column(String(100), default="")
    version: Mapped[str] = mapped_column(String(50), default="")
    effective_date: Mapped[str] = mapped_column(String(10), default="")  # YYYY-MM-DD
    language: Mapped[str] = mapped_column(String(5), default="")
    source_url: Mapped[str] = mapped_column(String(500), default="")
    file_name: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending / indexed / failed
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(200), default="")
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    vector_id: Mapped[str] = mapped_column(String(64), unique=True)

    document: Mapped[Document] = relationship(back_populates="chunks")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user / assistant
    country: Mapped[str] = mapped_column(String(8), default="")  # assistant: 답변 대상(ALL 또는 국가)
    content: Mapped[str] = mapped_column(Text)
    countries: Mapped[str] = mapped_column(String(100), default="")  # user: 선택한 국가 (쉼표 구분)
    mode: Mapped[str] = mapped_column(String(10), default="single")
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons: Mapped[str] = mapped_column(String(300), default="")  # 쉼표 구분 코드
    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    consistency: Mapped[float | None] = mapped_column(Float, nullable=True)
    model: Mapped[str] = mapped_column(String(50), default="")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
    citations: Mapped[list["MessageCitation"]] = relationship(
        back_populates="message", cascade="all, delete-orphan", order_by="MessageCitation.ref_no"
    )
    feedbacks: Mapped[list["Feedback"]] = relationship(back_populates="message", cascade="all, delete-orphan")


class MessageCitation(Base):
    __tablename__ = "message_citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[int | None] = mapped_column(ForeignKey("chunks.id", ondelete="SET NULL"), nullable=True)
    ref_no: Mapped[int] = mapped_column(Integer)
    cited: Mapped[bool] = mapped_column(Boolean, default=False)  # 답변 본문에서 실제로 인용했는지
    score: Mapped[float] = mapped_column(Float)

    message: Mapped[ChatMessage] = relationship(back_populates="citations")
    chunk: Mapped[Chunk | None] = relationship()


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True)
    rating: Mapped[str] = mapped_column(String(4))  # up / down
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    message: Mapped[ChatMessage] = relationship(back_populates="feedbacks")


class AnswerCache(Base):
    __tablename__ = "answer_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String(64), unique=True)
    response_json: Mapped[str] = mapped_column(Text)
    data_version: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Translation(Base):
    """근거 원문(영어·일본어)의 한국어 번역 캐시. 같은 청크는 한 번만 번역한다."""

    __tablename__ = "translations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"), unique=True)
    source_hash: Mapped[str] = mapped_column(String(64))  # 원문이 바뀌면(재색인) 다시 번역
    text_ko: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

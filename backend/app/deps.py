from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from rag.pipeline import RagPipeline

from .config import Settings


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_pipeline(request: Request) -> RagPipeline:
    return request.app.state.pipeline


def require_admin(
    settings: Settings = Depends(get_settings_dep),
    x_admin_token: str | None = Header(default=None),
) -> None:
    """ADMIN_TOKEN 이 설정돼 있으면 문서 등록·삭제 요청에 같은 토큰을 요구한다."""
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="관리자 토큰이 올바르지 않습니다.")

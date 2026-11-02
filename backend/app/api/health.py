from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
        db = "ok"
    except SQLAlchemyError:
        db = "unreachable"
    return {"status": "ok" if db == "ok" else "degraded", "db": db, "env": get_settings().env}

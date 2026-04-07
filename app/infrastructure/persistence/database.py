from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine = None
SessionLocal = sessionmaker(autoflush=False, autocommit=False, expire_on_commit=False)


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
        _engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
        SessionLocal.configure(bind=_engine)
    return _engine


def get_db_session() -> Session:
    get_engine()
    return SessionLocal()


def init_db() -> None:
    from app.infrastructure.persistence.models import Base

    Base.metadata.create_all(bind=get_engine())

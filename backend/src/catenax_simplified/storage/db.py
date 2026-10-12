from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .tables import Base


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite") and ":memory:" in url:
        # One shared connection, so every session sees the same in-memory database.
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def init_schema(engine: Engine) -> None:
    # Phase 1 creates the schema directly; migrations (Alembic) follow once the schema settles.
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)

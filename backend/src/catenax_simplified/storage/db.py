"""Database connection, sessions and schema migration."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .tables import Base


def make_engine(url: str) -> Engine:
    """An engine for the URL: SQLite (a file, or in memory for tests) or PostgreSQL in
    production. In-memory SQLite shares one connection so every session sees the same
    database.
    """
    if url.startswith("sqlite") and ":memory:" in url:
        # One shared connection, so every session sees the same in-memory database.
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def init_schema(engine: Engine) -> None:
    """Bring the database schema to the latest migration (Alembic)."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        if tables and "alembic_version" not in tables:
            # A database created before migrations existed (create_all): the schema only grew
            # by whole tables until then, so add any missing ones and record it as current.
            Base.metadata.create_all(connection)
            command.stamp(config, "head")
        else:
            command.upgrade(config, "head")


def make_session_factory(engine: Engine) -> sessionmaker:
    """Sessions that keep their objects usable after commit (``expire_on_commit=False``), so
    API handlers can return them.
    """
    return sessionmaker(bind=engine, expire_on_commit=False)

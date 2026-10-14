"""Alembic environment. The app runs migrations at startup (``storage.init_schema``) on its own
connection; the ``alembic`` command line uses ``CXS_DATABASE_URL`` (see ``backend/alembic.ini``)."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from catenax_simplified.storage.tables import Base

config = context.config
target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite cannot alter columns in place; batch mode recreates the table.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    url = os.environ.get("CXS_DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    engine = create_engine(url)
    with engine.connect() as conn:
        _run(conn)

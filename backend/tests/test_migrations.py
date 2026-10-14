from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from catenax_simplified.storage import Base, init_schema, make_engine
from catenax_simplified.storage.tables import PartRow


def test_migrations_produce_the_current_schema(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/fresh.db")
    init_schema(engine)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []
        assert context.get_current_revision() is not None


def test_init_schema_is_idempotent(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/twice.db")
    init_schema(engine)
    init_schema(engine)


def test_database_from_before_migrations_is_adopted(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/legacy.db")
    PartRow.__table__.create(engine)  # an early database: some tables, no alembic_version
    init_schema(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"parts", "notifications", "alembic_version"} <= tables

"""SQLAlchemy engine, session factory, and declarative base."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def ensure_columns() -> None:
    """Add columns that models gained since the database was created.

    SQLite's `create_all` creates missing tables but never alters existing
    ones, so a new nullable field would otherwise break inserts until the
    database was rebuilt. Only additive, nullable columns are handled here;
    anything structural still belongs in a real migration.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    added: set[tuple[str, str]] = set()
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have or column.primary_key:
                    continue
                if not column.nullable and column.default is None and column.server_default is None:
                    continue  # cannot be added safely; needs a real migration
                ddl = column.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}'))
                added.add((table.name, column.name))

        # A column added this way is NULL on every existing row, so anything
        # that queries on it needs a one-time backfill here.
        if ("score", "is_current") in added:
            conn.execute(text("UPDATE score SET is_current = 0"))
            conn.execute(text("""
                UPDATE score SET is_current = 1 WHERE score_id IN (
                    SELECT score_id FROM (
                        SELECT score_id, ROW_NUMBER() OVER (
                            PARTITION BY startup_id
                            ORDER BY computed_at DESC, score_id DESC) AS rn
                        FROM score
                    ) WHERE rn = 1
                )"""))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

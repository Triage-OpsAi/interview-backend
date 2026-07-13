import tempfile
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import settings


_engine = None


def _sqlite_url_for_path(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _tmp_sqlite_url() -> str:
    return _sqlite_url_for_path(Path(tempfile.gettempdir()) / "interview_agent.db")


def _engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


def _reset_engine(database_url: str) -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None
    settings.database_url = database_url


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))
    return _engine


def get_session():
    with Session(get_engine()) as session:
        yield session


def _run_compatibility_migrations() -> None:
    """Apply small additive migrations that create_all cannot add to existing tables."""
    engine = get_engine()
    additions = {
        "interview_links": {"round_number": "INTEGER NOT NULL DEFAULT 1"},
        "interviews": {"round_number": "INTEGER NOT NULL DEFAULT 1"},
        "interview_transcripts": {"response_mode": "VARCHAR NOT NULL DEFAULT 'voice'"},
    }
    dialect = engine.dialect.name

    with engine.begin() as connection:
        inspector = inspect(connection)
        existing_tables = set(inspector.get_table_names())
        for table_name, columns in additions.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in columns.items():
                if column_name in existing_columns:
                    continue
                if dialect == "postgresql":
                    statement = f'ALTER TABLE "{table_name}" ADD COLUMN IF NOT EXISTS "{column_name}" {definition}'
                else:
                    statement = f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {definition}'
                connection.execute(text(statement))


def init_db() -> None:
    from . import models  # noqa: F401

    try:
        SQLModel.metadata.create_all(get_engine())
        _run_compatibility_migrations()
    except Exception:
        if settings.database_url.startswith("sqlite") and "/tmp/" not in settings.database_url:
            _reset_engine(_tmp_sqlite_url())
            SQLModel.metadata.create_all(get_engine())
            _run_compatibility_migrations()
            return
        raise

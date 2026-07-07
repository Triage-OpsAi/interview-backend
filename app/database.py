import tempfile
from pathlib import Path

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


def init_db() -> None:
    from . import models  # noqa: F401

    try:
        SQLModel.metadata.create_all(get_engine())
    except Exception:
        if settings.database_url.startswith("sqlite") and "/tmp/" not in settings.database_url:
            _reset_engine(_tmp_sqlite_url())
            SQLModel.metadata.create_all(get_engine())
            return
        raise

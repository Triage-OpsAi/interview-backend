from sqlmodel import Session, SQLModel, create_engine

from .config import settings


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        engine_kwargs = {"pool_pre_ping": True}
        if settings.database_url.startswith("sqlite"):
            engine_kwargs = {"connect_args": {"check_same_thread": False}}
        _engine = create_engine(settings.database_url, **engine_kwargs)
    return _engine


def get_session():
    with Session(get_engine()) as session:
        yield session


def init_db() -> None:
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(get_engine())

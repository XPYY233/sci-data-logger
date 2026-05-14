from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel, create_engine

from sci_data_logger.config import Settings, get_settings
from sci_data_logger.db import models  # noqa: F401  ensure tables register


def get_engine(settings: Settings) -> Engine:
    storage_root = settings.ensure_storage()
    db_path = storage_root / "experiments.db"
    url = f"sqlite:///{db_path}"
    return create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},
    )


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@lru_cache
def get_engine_cached() -> Engine:
    return get_engine(get_settings())


def reset_engine_cache() -> None:
    """Dispose cached engine and clear the lru_cache (test helper)."""
    if get_engine_cached.cache_info().currsize:
        try:
            get_engine_cached().dispose()
        except Exception:
            pass
    get_engine_cached.cache_clear()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield a session, commit on success, rollback on error."""
    engine = get_engine_cached()
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

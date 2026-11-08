"""Engine/session management (shared by all domain modules)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


def make_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    return create_engine(url, pool_pre_ping=True, future=True)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def reset_engine() -> None:
    """Drop the cached engine (used by tests to rebind DATABASE_URL)."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_exists(admin_url: str, dbname: str) -> bool:
    engine = make_engine(admin_url)
    try:
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": dbname}
                ).scalar()
            )
    finally:
        engine.dispose()


def create_database(admin_url: str, dbname: str) -> None:
    engine = make_engine(admin_url)
    try:
        with engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT")
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": dbname}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()


def drop_database(admin_url: str, dbname: str) -> None:
    engine = make_engine(admin_url)
    try:
        with engine.connect() as conn:
            conn.execution_options(isolation_level="AUTOCOMMIT")
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": dbname}
            ).scalar()
            if exists:
                conn.execute(text(f'DROP DATABASE "{dbname}" WITH (FORCE)'))
    finally:
        engine.dispose()

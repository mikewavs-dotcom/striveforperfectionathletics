from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_settings

_PSYCOPG_PREFIX = "postgresql+psycopg://"
_POSTGRES_PREFIXES = ("postgresql://", "postgres://")


def normalize_database_url(url: str) -> str:
    stripped = url.strip()
    if stripped.startswith(_PSYCOPG_PREFIX):
        return stripped
    for prefix in _POSTGRES_PREFIXES:
        if stripped.startswith(prefix):
            return f"{_PSYCOPG_PREFIX}{stripped[len(prefix):]}"
    return stripped


def get_engine() -> Engine:
    return create_engine(normalize_database_url(get_settings().database_url), future=True)


def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

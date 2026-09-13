from types import SimpleNamespace

import pytest

from backend.app.db import get_engine, normalize_database_url


def test_normalize_postgresql_to_psycopg() -> None:
    assert (
        normalize_database_url("postgresql://user:pass@localhost:5432/app")
        == "postgresql+psycopg://user:pass@localhost:5432/app"
    )


def test_normalize_postgres_to_psycopg() -> None:
    assert (
        normalize_database_url("postgres://user:pass@localhost:5432/app")
        == "postgresql+psycopg://user:pass@localhost:5432/app"
    )


def test_normalize_keeps_psycopg_and_query() -> None:
    already = "postgresql+psycopg://user:pass@localhost/app?sslmode=require"
    assert normalize_database_url(already) == already
    assert (
        normalize_database_url("postgresql://user:pass@localhost/app?sslmode=require")
        == "postgresql+psycopg://user:pass@localhost/app?sslmode=require"
    )


def test_get_engine_uses_psycopg_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("backend.app.db.create_engine", fake_create_engine)
    monkeypatch.setattr(
        "backend.app.db.get_settings",
        lambda: SimpleNamespace(database_url="postgresql://user:pass@localhost/app"),
    )
    get_engine()
    assert captured["url"] == "postgresql+psycopg://user:pass@localhost/app"

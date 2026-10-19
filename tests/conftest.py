"""Shared fixtures: a fresh app on an in-memory SQLite database for each test."""
import pytest

from app import create_app, db


def _make_app(monkeypatch, behind_tls_proxy):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    if behind_tls_proxy:
        monkeypatch.setenv("BEHIND_TLS_PROXY", "1")
    else:
        monkeypatch.delenv("BEHIND_TLS_PROXY", raising=False)
    app = create_app()
    with app.app_context():
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def app(monkeypatch):
    yield from _make_app(monkeypatch, behind_tls_proxy=False)


@pytest.fixture
def tls_app(monkeypatch):
    """The app as it runs in Docker, behind the nginx TLS proxy (Req 6)."""
    yield from _make_app(monkeypatch, behind_tls_proxy=True)


@pytest.fixture
def client(app):
    return app.test_client()

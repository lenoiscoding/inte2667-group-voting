def test_health(client):
    # Uses the shared in-memory test database, not instance/dev.db.
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_fails_when_the_database_is_unreachable(client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app import db

    def unreachable(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(db.session, "execute", unreachable)
    resp = client.get("/health")
    assert resp.status_code == 503 and resp.get_json() == {"status": "error"}

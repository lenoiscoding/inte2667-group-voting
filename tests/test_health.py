def test_health(client):
    # Uses the shared in-memory test database, not instance/dev.db.
    resp = client.get("/health")
    assert resp.status_code == 200

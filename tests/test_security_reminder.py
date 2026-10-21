from app import create_app


def test_login_page_displays_security_reminder(tmp_path, monkeypatch):
    database_path = tmp_path / "test_security_reminder.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")

    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    response = client.get("/auth/login")

    assert response.status_code == 200
    assert b"Security reminder:" in response.data
    assert b"Never share your password or authenticator code" in response.data
    assert b"We will never ask you to disclose your one-time code." in response.data

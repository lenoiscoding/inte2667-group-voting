import time
from datetime import datetime, timezone

import pyotp
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.auth.models.user import User


def test_previous_successful_login_is_displayed(tmp_path, monkeypatch):
    database_path = tmp_path / "test_login.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")

    app = create_app()
    app.config["TESTING"] = True

    previous_login = datetime(2026, 1, 15, 10, 30, tzinfo=timezone.utc)
    secret = pyotp.random_base32()

    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(
            username="r12_test_user",
            password_hash=generate_password_hash("TestPassword123!"),
            role="voter",
            is_active=True,
            mfa=True,
            totp_secret=secret,
            last_successful_login=previous_login,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.user_id

    client = app.test_client()

    response = client.post(
        "/auth/login",
        data={"username": "r12_test_user", "password": "TestPassword123!"},
    )
    assert response.status_code == 200
    assert b"otp" in response.data.lower()

    otp = pyotp.TOTP(secret).now()
    response = client.post("/auth/login", data={"otp": otp})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/home")

    response = client.get("/auth/home")
    assert response.status_code == 200
    assert b"2026-01-15T10:30:00" in response.data

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.last_successful_login is not None
        assert user.last_successful_login != previous_login

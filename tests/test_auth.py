"""Req 1, 2 and 3: two-factor login, account lockout and idle timeout."""
import time

import pyotp
import pytest
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.auth.models.user import User

PASSWORD = "CorrectHorse12!"


@pytest.fixture
def user(app):
    app.config.update(LOCKOUT_MAX_ATTEMPTS=3, LOCKOUT_WINDOW_SECONDS=60, LOCKOUT_SECONDS=30)
    account = User(username="voter", password_hash=generate_password_hash(PASSWORD),
                   role="voter", totp_secret=pyotp.random_base32())
    db.session.add(account)
    db.session.commit()
    return account


def sign_in(client, password=PASSWORD):
    return client.post("/auth/login", data={"username": "voter", "password": password})


def enter_code(client, code):
    return client.post("/auth/login", data={"otp": code})


def logged_in(client, user, idle_seconds=0):
    with client.session_transaction() as session:
        session["authenticated_user_id"] = user.user_id
        session["last_activity"] = time.time() - idle_seconds


def test_login_wrong_password(client):
    response = client.post("/auth/login", data={"username": "nobody", "password": "WrongPassword123!"})
    assert response.status_code == 200 and b"Invalid username or password" in response.data


def test_password_alone_does_not_log_in(client, user):
    assert b'name="otp"' in sign_in(client).data
    assert client.get("/auth/home").status_code == 302


def test_password_and_authenticator_code_log_in(client, user):
    sign_in(client)
    response = enter_code(client, pyotp.TOTP(user.totp_secret).now())
    assert response.headers["Location"].endswith("/auth/home")


def test_wrong_passwords_lock_the_account(client, user):
    for _ in range(3):
        response = sign_in(client, "wrong-password")
    assert b"locked for 30 seconds" in response.data
    assert b"temporarily locked" in sign_in(client).data  # right password, still locked


def test_wrong_authenticator_codes_also_lock_the_account(client, user):
    sign_in(client)
    for _ in range(3):
        response = enter_code(client, "000000")
    assert b"locked for 30 seconds" in response.data
    assert b'name="otp"' not in response.data  # has to start again
    assert b"temporarily locked" in sign_in(client).data


def test_idle_session_expires(app, client, user):
    timeout = app.config["SESSION_TIMEOUT_SECONDS"]
    logged_in(client, user, idle_seconds=timeout - 5)
    assert client.get("/auth/home").status_code == 200
    logged_in(client, user, idle_seconds=timeout + 1)
    assert client.get("/auth/home").headers["Location"].endswith("/auth/login")
    assert client.get("/voting/ballot").headers["Location"].endswith("/auth/login")


def test_logout_ends_the_session(client, user):
    logged_in(client, user)
    assert client.post("/auth/logout").headers["Location"].endswith("/auth/login")
    assert client.get("/auth/home").status_code == 302


def test_timings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SESSION_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("LOCKOUT_SECONDS", "")  # blank -> the report's value
    app = create_app()
    assert app.config["SESSION_TIMEOUT_SECONDS"] == 60 and app.config["LOCKOUT_SECONDS"] == 900


def test_deployment_refuses_to_start_without_its_keys(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("BEHIND_TLS_PROXY", "1")
    for name in ("SECRET_KEY", "JWT_SECRET_KEY", "AES_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="AES_KEY"):
        create_app()

"""Req 6: ballot data travels only over TLS.

nginx terminates TLS (nginx/default.conf). These tests check that config and
the app's side of it: behind the proxy the app trusts the forwarded scheme and
client IP, marks the session cookie Secure, and refuses voting requests that
did not arrive over HTTPS.
"""
import re
from pathlib import Path

import pyotp
from flask import url_for
from werkzeug.security import generate_password_hash

from app import db
from app.auth.models.login_attempt import LoginAttempt
from app.auth.models.user import User

HTTPS = {"X-Forwarded-Proto": "https"}
PASSWORD = "correct horse battery"


def _add_user():
    db.session.add(User(
        username="ann",
        password_hash=generate_password_hash(PASSWORD),
        role="voter",
        totp_secret=pyotp.random_base32(),
    ))
    db.session.commit()


def test_proxy_redirects_http_and_allows_only_modern_tls():
    conf = (Path(__file__).parents[1] / "nginx" / "default.conf").read_text()
    assert "return 301 https://" in conf
    assert re.search(r"ssl_protocols\s+TLSv1\.2 TLSv1\.3;", conf)
    assert "Strict-Transport-Security" in conf


def test_voting_refuses_plain_http(tls_app):
    with tls_app.test_request_context():
        url = url_for("voting.ping")
    client = tls_app.test_client()
    assert client.get(url).status_code == 403
    assert client.get(url, headers=HTTPS).status_code == 200


def test_session_cookie_is_https_only(tls_app):
    _add_user()
    resp = tls_app.test_client().post(
        "/auth/login",
        data={"username": "ann", "password": PASSWORD},
        headers=HTTPS,
    )
    assert "Secure" in resp.headers["Set-Cookie"]


def test_login_log_records_real_client_ip(tls_app):
    _add_user()
    tls_app.test_client().post(
        "/auth/login",
        data={"username": "ann", "password": "wrong"},
        headers={**HTTPS, "X-Forwarded-For": "203.0.113.7"},
    )
    assert LoginAttempt.query.one().source_ip == "203.0.113.7"

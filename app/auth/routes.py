from datetime import datetime, timezone, timedelta
import time

import pyotp
from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from app import db
from app.auth.models.login_attempt import LoginAttempt
from app.auth.models.user import User
from app.auth.session_guard import active_user_id
from app.storage.integration import record_event


auth_bp = Blueprint("auth", __name__)


def _as_utc(moment):
    """SQLite returns naive datetimes; PostgreSQL returns timezone-aware ones."""
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _is_locked(user, now):
    return user.lockedout_until is not None and _as_utc(user.lockedout_until) > now


def _duration(seconds):
    if seconds >= 60 and seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    return f"{seconds} second{'s' if seconds != 1 else ''}"


def _record_failure(user, now, reason):
    """Req 2 and 4: log a failed attempt, and lock the account after too many.

    Wrong passwords and wrong authenticator codes both count, so the lock also
    stops anyone guessing codes. Returns the lock message, or None.
    """
    settings = current_app.config
    db.session.add(
        LoginAttempt(
            user_id=user.user_id,
            timestamp=now,
            source_ip=request.remote_addr,
            outcome="denied",
            failure_reason=reason,
        )
    )
    db.session.flush()

    recent_failures = LoginAttempt.query.filter(
        LoginAttempt.user_id == user.user_id,
        LoginAttempt.outcome == "denied",
        LoginAttempt.timestamp
        >= now - timedelta(seconds=settings["LOCKOUT_WINDOW_SECONDS"]),
    ).count()
    locked = recent_failures >= settings["LOCKOUT_MAX_ATTEMPTS"]
    if locked:
        user.lockedout_until = now + timedelta(seconds=settings["LOCKOUT_SECONDS"])
    db.session.commit()

    record_event("LOGIN_FAILED", user.user_id, ip=request.remote_addr, reason=reason)
    if not locked:
        return None
    record_event("ACCOUNT_LOCKED", user.user_id, ip=request.remote_addr)
    return (
        "Too many failed attempts. The account is locked for "
        f"{_duration(settings['LOCKOUT_SECONDS'])}."
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    message = ""
    show_otp = "pending_mfa_user_id" in session
    now = datetime.now(timezone.utc)

    if request.method == "POST":
        if "otp" in request.form:
            user_id = session.get("pending_mfa_user_id")
            user = db.session.get(User, user_id) if user_id else None

            if user is None:
                session.pop("pending_mfa_user_id", None)
                message, show_otp = "Please sign in again.", False

            elif _is_locked(user, now):
                # Req 2: a locked account cannot keep trying codes either.
                session.pop("pending_mfa_user_id", None)
                message, show_otp = "Account is temporarily locked.", False

            elif user.totp_secret and pyotp.TOTP(user.totp_secret).verify(
                request.form.get("otp", ""), valid_window=1
            ):
                # R12: Save the previous successful login before updating it.
                previous_login = user.last_successful_login
                user.last_successful_login = now
                db.session.flush()

                db.session.add(
                    LoginAttempt(
                        user_id=user.user_id,
                        timestamp=now,
                        source_ip=request.remote_addr,
                        outcome="success",
                    )
                )
                db.session.commit()

                record_event("LOGIN_SUCCESS", user.user_id, ip=request.remote_addr)

                # A fresh session after login (stops session fixation).
                session.clear()
                session["authenticated_user_id"] = user.user_id
                session["last_activity"] = time.time()
                session["previous_successful_login"] = (
                    previous_login.isoformat() if previous_login else None
                )

                return redirect(url_for("auth.home"))

            else:
                locked_message = _record_failure(user, now, "invalid authenticator code")
                if locked_message:
                    session.pop("pending_mfa_user_id", None)
                    message, show_otp = locked_message, False
                else:
                    message, show_otp = "Invalid authenticator code. Try again.", True

        else:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()

            if not user or not check_password_hash(user.password_hash, password):
                message = "Invalid username or password."
                if user:
                    message = _record_failure(user, now, "incorrect password") or message
                else:
                    record_event(
                        "LOGIN_FAILED",
                        "unknown",
                        ip=request.remote_addr,
                        reason="unknown username",
                    )

            elif not user.is_active:
                message = "Account is inactive."

            elif _is_locked(user, now):
                message = "Account is temporarily locked."

            elif not user.totp_secret:
                message = "Authenticator has not been configured."

            else:
                session["pending_mfa_user_id"] = user.user_id
                show_otp = True

    return render_template("login.html", message=message, show_otp=show_otp)


@auth_bp.route("/home")
def home():
    if not active_user_id():
        return redirect(url_for("auth.login"))
    return render_template(
        "home.html",
        previous_successful_login=session.get("previous_successful_login"),
    )


@auth_bp.route("/activity", methods=["POST"])
def update_activity():
    """Req 3: the page's script reports activity, which keeps the session alive."""
    if not active_user_id():
        return jsonify({"expired": True}), 401
    return jsonify({"ok": True})


@auth_bp.route("/logout", methods=["POST"])
def logout():
    user_id = session.get("authenticated_user_id")
    session.clear()
    if user_id:
        record_event("LOGOUT", user_id, ip=request.remote_addr)
    return redirect(url_for("auth.login"))

from datetime import datetime, timezone, timedelta
import pyotp
import time
from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify
from werkzeug.security import check_password_hash
from app import db
from app.auth.models.user import User
from app.auth.models.login_attempt import LoginAttempt

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    message = ""
    show_otp = "pending_mfa_user_id" in session
    now = datetime.now(timezone.utc)

    if request.method == "POST":

        if "otp" in request.form:
            user_id = session.get("pending_mfa_user_id")
            user = db.session.get(User, user_id) if user_id else None

            if user and user.totp_secret and pyotp.TOTP(
                user.totp_secret
            ).verify(request.form.get("otp", ""), valid_window=1):

                db.session.add(LoginAttempt(
                    user_id=user.user_id,
                    timestamp=now,
                    source_ip=request.remote_addr,
                    outcome="success"
                ))
                db.session.commit()

                session.clear()
                session["authenticated_user_id"] = user.user_id
                session["last_activity"] = time.time()

                return redirect(url_for("auth.home"))

            else:
                if user:
                    db.session.add(LoginAttempt(
                        user_id=user.user_id,
                        timestamp=now,
                        source_ip=request.remote_addr,
                        outcome="denied",
                        failure_reason="invalid authenticator code"
                    ))
                    db.session.commit()

                message = "Invalid authenticator code. Try again."
                show_otp = True

        else:
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()

            if not user or not check_password_hash(
                user.password_hash, password
            ):
                message = "Invalid username or password."

                if user:
                    db.session.add(LoginAttempt(
                        user_id=user.user_id,
                        timestamp=now,
                        source_ip=request.remote_addr,
                        outcome="denied",
                        failure_reason="incorrect password"
                    ))
                    db.session.flush()

                    attempts = LoginAttempt.query.filter(
                        LoginAttempt.user_id == user.user_id,
                        LoginAttempt.failure_reason == "incorrect password",
                        LoginAttempt.timestamp >= now - timedelta(minutes=1)
                    ).count()

                    if attempts >= 3:
                        user.lockedout_until = now + timedelta(seconds=5)
                        message = "Account locked for 5 seconds."

                    db.session.commit()

            elif not user.is_active:
                message = "Account is inactive."

            elif user.lockedout_until and user.lockedout_until > now:
                message = "Account is temporarily locked."

            elif not user.totp_secret:
                message = "Authenticator has not been configured."

            else:
                session["pending_mfa_user_id"] = user.user_id
                show_otp = True

    return render_template(
        "login.html",
        message=message,
        show_otp=show_otp
    )


@auth_bp.route("/home")
def home():
    user_id = session.get("authenticated_user_id")
    last_activity = session.get("last_activity", 0)

    if not user_id or time.time() - last_activity >= 10:
        session.clear()
        return redirect(url_for("auth.login"))

    return render_template("home.html")


@auth_bp.route("/activity", methods=["POST"])
def update_activity():
    user_id = session.get("authenticated_user_id")
    last_activity = session.get("last_activity", 0)

    if not user_id or time.time() - last_activity >= 10:
        session.clear()
        return jsonify({"expired": True}), 401

    session["last_activity"] = time.time()
    return jsonify({"ok": True})


from datetime import datetime, timezone, timedelta

from flask import Blueprint, render_template, request
from werkzeug.security import check_password_hash

from app import db
from app.auth.models.user import User
from app.auth.models.login_attempt import LoginAttempt

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    message = ""

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user is None:
            message = "User not found"

        else:
            now = datetime.now(timezone.utc)
            if user.lockedout_until and user.lockedout_until > now:
                login_attempt = LoginAttempt(
                    user_id=user.user_id,
                    source_ip=request.remote_addr,
                    outcome="denied",
                    failure_reason="locked out"
                )
                db.session.add(login_attempt)
                db.session.commit()

                message = "Account is temporarily locked"

            else:
                if check_password_hash(user.password_hash, password):
                    login_attempt = LoginAttempt(
                        user_id=user.user_id,
                        source_ip=request.remote_addr,
                        outcome="success",
                        failure_reason=None
                    )
                    db.session.add(login_attempt)
                    db.session.commit()

                    message = "Login successful"

                else:
                    login_attempt = LoginAttempt(
                        user_id=user.user_id,
                        source_ip=request.remote_addr,
                        outcome="denied",
                        failure_reason="incorrect password"
                    )

                    db.session.add(login_attempt)

                    one_minute_ago = now - timedelta(minutes=1)

                    failed_attempts = LoginAttempt.query.filter(
                        LoginAttempt.user_id == user.user_id,
                        LoginAttempt.outcome == "denied",
                        LoginAttempt.failure_reason == "incorrect password",
                        LoginAttempt.timestamp >= one_minute_ago
                    ).count()

                    if failed_attempts >= 3:
                        user.lockedout_until = now + timedelta(seconds=5)
                        message = "Too many incorrect passwords. Account locked for 5 seconds."
                    else:
                        message = "Incorrect password"
                    db.session.commit()

    return render_template("login.html", message=message)
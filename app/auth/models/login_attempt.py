from datetime import datetime, timezone
from app import db


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"

    attempt_id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id"),
        nullable=False
    )

    timestamp = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    source_ip = db.Column(
        db.String(45),
        nullable=False
    )

    outcome = db.Column(
        db.String(20),
        nullable=False
    )

    failure_reason = db.Column(
        db.String(100),
        nullable=True
    )

    def __repr__(self):
        return f"<LoginAttempt {self.attempt_id} - {self.outcome}>"
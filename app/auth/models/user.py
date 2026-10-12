from app import db
from datetime import datetime, timezone


class User(db.Model):
    __tablename__ = "users"

    user_id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    mfa = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    role = db.Column(
        db.String(50),
        nullable=False
    )

    is_active = db.Column(
        db.Boolean,
        default=True,
        nullable=False
    )

    lockedout_until = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    last_successful_login = db.Column(
        db.DateTime(timezone=True),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    totp_secret = db.Column(
        db.String(32), 
        nullable=True
    )
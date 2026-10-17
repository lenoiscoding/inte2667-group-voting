
from datetime import datetime, timezone

from app import db


class RegistrationChange(db.Model):
    """Audit history for changes to a voter's registration details."""

    __tablename__ = "registration_changes"

    change_id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id"),
        nullable=False,
        index=True,
    )

    field_name = db.Column(db.String(50), nullable=False)
    old_value = db.Column(db.String(255), nullable=False)
    new_value = db.Column(db.String(255), nullable=False)

    changed_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

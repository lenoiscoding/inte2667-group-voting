
from datetime import datetime, timezone

from app import db
from app.storage.integration import EncryptedText


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
    # Req 8: old and new names/addresses are personal details too.
    old_value = db.Column(EncryptedText, nullable=False)
    new_value = db.Column(EncryptedText, nullable=False)

    changed_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

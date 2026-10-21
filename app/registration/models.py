import secrets
from datetime import datetime, timezone

from app import db
from app.storage.integration import EncryptedDate, EncryptedText


def generate_voter_ref():
    """Random, non-sequential voter reference (cannot be guessed or enumerated)."""
    return "V" + secrets.token_hex(8).upper()


class VoterRecord(db.Model):
    __tablename__ = "voter_records"

    voter_id = db.Column(db.Integer, primary_key=True)

    # System-generated public reference. Never typed in by the voter.
    voter_ref = db.Column(
        db.String(20),
        unique=True,
        nullable=False,
        default=generate_voter_ref,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id"),
        unique=True,
        nullable=False,
    )

    # Req 8: personal details are stored encrypted.
    full_name = db.Column(EncryptedText, nullable=False)
    date_of_birth = db.Column(EncryptedDate, nullable=False)
    address = db.Column(EncryptedText, nullable=False)

    # Identity document number used for the duplicate registration check.
    id_document_number = db.Column(
        db.String(50),
        unique=True,
        nullable=False,
    )

    registered_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f"<VoterRecord {self.voter_id}>"
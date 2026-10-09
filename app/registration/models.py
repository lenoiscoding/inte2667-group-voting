from datetime import datetime, timezone

from app import db


class VoterRecord(db.Model):
    __tablename__ = "voter_records"

    voter_id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.user_id"),
        unique=True,
        nullable=False
    )

    full_name = db.Column(db.String(150), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    address = db.Column(db.String(255), nullable=False)

    # Identity document number, used for the duplicate registration check
    id_number = db.Column(db.String(50), unique=True, nullable=False)

    registered_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def __repr__(self):
        return f"<VoterRecord {self.voter_id}>"

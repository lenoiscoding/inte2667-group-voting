"""Req 7: one vote per voter per election.

VoterParticipation is the "has voted" record. Its unique constraint makes the
database itself refuse a second ballot for the same voter, even when two
requests race. The ballot is then cast with a random one-time token:
ballot_tokens and ballots hold no voter ID, IP address or timestamp, so a
stored ballot cannot be traced back to the voter (the same design as Req 10).
"""
import secrets

from app import db


class VoterParticipation(db.Model):
    __tablename__ = "voter_participation"
    __table_args__ = (
        db.UniqueConstraint("election_id", "voter_id", name="uq_one_ballot_per_voter"),
    )

    participation_id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.String(32), nullable=False)
    voter_id = db.Column(
        db.Integer, db.ForeignKey("voter_records.voter_id"), nullable=False
    )
    # Hash of the voter's current token, so an unused one can be replaced if
    # the ballot page is lost. Ballots never store it, so it links to nothing.
    token_hash = db.Column(db.String(64), nullable=False)


class BallotToken(db.Model):
    """Unused one-time tokens. Only the SHA-256 hash is stored."""

    __tablename__ = "ballot_tokens"

    token_hash = db.Column(db.String(64), primary_key=True)
    election_id = db.Column(db.String(32), nullable=False)


class Ballot(db.Model):
    __tablename__ = "ballots"

    ballot_id = db.Column(
        db.String(32), primary_key=True, default=lambda: secrets.token_hex(16)
    )
    election_id = db.Column(db.String(32), nullable=False)
    house_prefs = db.Column(db.Text, nullable=False)  # JSON {candidate: number}
    senate_prefs = db.Column(db.Text)  # for the Senate ballot (Req 18)

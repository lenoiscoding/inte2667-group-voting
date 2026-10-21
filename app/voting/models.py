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


class ElectionStatus(db.Model):
    """Req 19: whether the polls are open. No row means they are open."""

    __tablename__ = "election_status"

    election_id = db.Column(db.String(32), primary_key=True)
    polls_open = db.Column(db.Boolean, nullable=False, default=True)
    closed_at = db.Column(db.String(32))


class CountCheckpoint(db.Model):
    """Req 19: the saved progress of a vote count (see app/voting/counting.py)."""

    __tablename__ = "count_checkpoints"

    election_id = db.Column(db.String(32), primary_key=True)
    phase = db.Column(db.String(20), nullable=False)  # TALLYING or COMPLETE
    ballots_counted = db.Column(db.Integer, nullable=False)
    # Ballots are counted in ballot_id order; this is the last one counted.
    last_ballot_id = db.Column(db.String(32))
    state_json = db.Column(db.Text, nullable=False)  # running totals, then the result
    updated_at = db.Column(db.String(32), nullable=False)
    checkpoint_hmac = db.Column(db.String(64), nullable=False)

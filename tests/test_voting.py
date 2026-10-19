"""Req 7: each registered voter can vote only once per election."""
import re
import time
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app import db
from app.auth.models.user import User
from app.registration.models import VoterRecord
from app.voting.models import Ballot, BallotToken, VoterParticipation
from app.voting.routes import ELECTION_ID, HOUSE_CANDIDATES

FULL_BALLOT = {f"pref_{i}": str(i + 1) for i in range(len(HOUSE_CANDIDATES))}


@pytest.fixture
def voter(client):
    """A registered voter, logged in on `client`."""
    user = User(username="voter1", password_hash="unused", role="voter")
    db.session.add(user)
    db.session.flush()
    record = VoterRecord(
        user_id=user.user_id,
        full_name="Test Voter",
        date_of_birth=date(1990, 1, 1),
        address="1 Test St",
        id_document_number="TEST123",
    )
    db.session.add(record)
    db.session.commit()
    with client.session_transaction() as s:
        s["authenticated_user_id"] = user.user_id
        s["last_activity"] = time.time()
    return record


def open_ballot(client):
    """Load the ballot page and return its one-time token (None if refused)."""
    html = client.get("/voting/ballot").get_data(as_text=True)
    match = re.search(r'name="ballot_token" value="([^"]+)"', html)
    return match.group(1) if match else None


def cast(client, token, ballot=FULL_BALLOT):
    return client.post("/voting/ballot", data={**ballot, "ballot_token": token})


def test_voter_can_vote_only_once(client, voter):
    assert cast(client, open_ballot(client)).status_code == 200
    assert open_ballot(client) is None
    assert "already voted" in client.get("/voting/ballot").get_data(as_text=True)
    assert Ballot.query.count() == 1


def test_used_token_cannot_be_replayed(client, voter):
    token = open_ballot(client)
    cast(client, token)
    assert cast(client, token).status_code == 409
    assert Ballot.query.count() == 1


def test_reopening_ballot_replaces_the_token(client, voter):
    old, new = open_ballot(client), open_ballot(client)
    assert cast(client, old).status_code == 409
    assert cast(client, new).status_code == 200
    assert Ballot.query.count() == 1


def test_incomplete_ballot_keeps_the_token(client, voter):
    token = open_ballot(client)
    assert cast(client, token, {"pref_0": "1"}).status_code == 400
    assert cast(client, token).status_code == 200


def test_database_refuses_a_second_has_voted_record(voter):
    for token_hash in ("a" * 64, "b" * 64):
        db.session.add(VoterParticipation(
            election_id=ELECTION_ID, voter_id=voter.voter_id, token_hash=token_hash
        ))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_stored_ballot_has_no_link_to_the_voter(client, voter):
    cast(client, open_ballot(client))
    assert set(Ballot.__table__.columns.keys()) == {
        "ballot_id", "election_id", "house_prefs", "senate_prefs"
    }
    assert BallotToken.query.count() == 0  # the used token is deleted

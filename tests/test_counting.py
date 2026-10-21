"""Req 19: a checkpointed count that survives a crash and detects tampering."""
import json

import pytest
from sqlalchemy import text

from app import db
from app.storage.integration import AuditLog
from app.voting.ballot_papers import ELECTION_ID, HOUSE_CANDIDATES
from app.voting.counting import (CountError, SimulatedCrash, close_polls,
                                 polls_open, run_count)
from app.voting.models import Ballot, CountCheckpoint
from tests.test_voting import cast, open_ballot, voter  # noqa: F401 (fixture)

AVERY, JORDAN, PRIYA, SAM = HOUSE_CANDIDATES
SENATE_A_FIRST = {"method": "ATL", "preferences": {code: n for n, code in enumerate("ABCDEF", 1)}}

# Avery leads on first preferences, but Priya's votes flow to Jordan, who wins.
ORDERS = ([[AVERY, JORDAN, PRIYA, SAM]] * 3 + [[JORDAN, AVERY, PRIYA, SAM]] * 2
          + [[PRIYA, JORDAN, AVERY, SAM]] * 2)


def make_ballot(order, ballot_id=None):
    return Ballot(
        ballot_id=ballot_id, election_id=ELECTION_ID,
        house_prefs=json.dumps({name: n for n, name in enumerate(order, 1)}),
        senate_prefs=json.dumps(SENATE_A_FIRST),
    )


@pytest.fixture
def ballots(app):
    db.session.add_all(make_ballot(order) for order in ORDERS)
    # An informal ballot (every House box numbered 1, no Senate vote).
    db.session.add(Ballot(election_id=ELECTION_ID,
                          house_prefs=json.dumps(dict.fromkeys(HOUSE_CANDIDATES, 1))))
    db.session.commit()


def assert_correct_result(row):
    state = json.loads(row.state_json)
    assert row.phase == "COMPLETE" and row.ballots_counted == 8
    assert state["informal_house"] == 1 and state["informal_senate"] == 1
    assert state["senate"] == {"A": 7}
    assert state["result"]["elected"] == JORDAN
    assert [r["excluded"] for r in state["result"]["rounds"]] == [SAM, PRIYA, None]


def test_count_waits_for_the_polls_to_close(ballots):
    with pytest.raises(CountError):
        run_count()


def test_uninterrupted_count(ballots):
    close_polls()
    assert_correct_result(run_count(batch_size=3))


def test_count_resumes_after_a_crash_without_double_counting(ballots):
    close_polls()
    with pytest.raises(SimulatedCrash):
        run_count(batch_size=2, crash_after=5)
    saved = db.session.get(CountCheckpoint, ELECTION_ID)
    assert saved.phase == "TALLYING" and saved.ballots_counted == 4  # the last checkpoint
    assert_correct_result(run_count(batch_size=2))


def test_tampered_checkpoint_is_detected_and_recounted(ballots):
    close_polls()
    with pytest.raises(SimulatedCrash):
        run_count(batch_size=2, crash_after=5)
    db.session.execute(text("UPDATE count_checkpoints SET ballots_counted = ballots_counted + 100"))
    db.session.commit()
    assert_correct_result(run_count())
    assert AuditLog.query.filter_by(event_type="COUNT_CHECKPOINT_REJECTED").count() == 1


def test_ballot_added_mid_count_is_caught_not_lost(ballots):
    close_polls()
    with pytest.raises(SimulatedCrash):
        run_count(batch_size=2, crash_after=3)
    db.session.add(make_ballot(ORDERS[0], ballot_id="0" * 32))  # sorts before the checkpoint
    db.session.commit()
    with pytest.raises(CountError):
        run_count(batch_size=2)  # 8 counted but 9 stored: discarded
    assert run_count(batch_size=2).ballots_counted == 9  # recounted from the start


def test_no_ballots_are_accepted_once_the_polls_close(client, voter):
    token = open_ballot(client)
    close_polls()
    assert not polls_open()
    assert cast(client, token).status_code == 403
    assert "Voting has closed" in client.get("/voting/ballot").get_data(as_text=True)
    assert Ballot.query.count() == 0


def test_results_page_withholds_tampered_results(client, ballots):
    assert "not available yet" in client.get("/voting/results").get_data(as_text=True)
    close_polls()
    run_count()
    assert "Elected: Jordan Lee" in client.get("/voting/results").get_data(as_text=True)
    db.session.execute(
        text("UPDATE count_checkpoints SET state_json = REPLACE(state_json, :old, :new)"),
        {"old": '"elected":"Jordan Lee"', "new": '"elected":"Sam Walker"'})
    db.session.commit()
    page = client.get("/voting/results").get_data(as_text=True)
    assert "Results withheld" in page and "Elected:" not in page


def test_count_votes_command_crash_and_resume(app, ballots):
    runner = app.test_cli_runner()
    assert "Polls closed" in runner.invoke(args=["close-polls"]).output
    crashed = runner.invoke(args=["count-votes", "--batch-size", "2", "--crash-after", "5"])
    assert crashed.exit_code == 1 and "simulated crash" in crashed.output
    resumed = runner.invoke(args=["count-votes", "--batch-size", "2"])
    assert "Resuming from the checkpoint: 4 ballots already counted." in resumed.output
    assert "Elected: Jordan Lee" in resumed.output

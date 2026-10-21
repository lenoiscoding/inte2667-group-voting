"""Req 19: a checkpointed vote count that can resume after a crash.

The count is a small state machine, TALLYING -> COMPLETE, run by an election
official once the polls are closed (flask --app run count-votes).

* Ballots are read in ballot_id order, one batch at a time. After each batch
  the running totals and the ID of the last ballot counted are saved together,
  in one row and one transaction. After a crash the count carries on from that
  checkpoint, so no ballot is counted twice and none is skipped. The ballots
  themselves are never changed.
* Each checkpoint carries an HMAC-SHA256 tag keyed with the app's SECRET_KEY.
  Anyone who edits the saved totals in the database cannot make a matching
  tag, so the edit is detected and the count starts again from the ballots.
* Before the count finishes, the number of ballots counted is checked against
  the number stored, so a ballot added or removed mid-count is caught.
* Every ballot is validated again as it is counted (Req 17 and 18); anything
  that is not formal is set aside as informal.

House seats use a full preferential count. The Senate shows first
preferences by group; a full Senate quota count is outside the prototype.

Built from Sahil's ResultsComputationEngine and CheckpointStore
(requirements_17-20.py), moved into the app's own database.
"""
import hashlib
import hmac
import json

import click
from flask import current_app
from flask.cli import with_appcontext

from app import db
from app.storage.integration import record_event
from app.storage.storage import _now_iso
from app.voting.ballot_papers import (ELECTION_ID, HOUSE_CANDIDATES,
                                      SENATE_CANDIDATE_GROUP, SENATE_GROUPS,
                                      SENATE_POLICY)
from app.voting.models import Ballot, CountCheckpoint, ElectionStatus
from app.voting.validation import validate_house_ballot, validate_senate_line

TALLYING, COMPLETE = "TALLYING", "COMPLETE"
OFFICIAL = "election-official"  # audit log actor for these commands


class CountError(RuntimeError):
    """The count cannot start or finish. The message says why."""


class SimulatedCrash(RuntimeError):
    """Raised by --crash-after, to show recovery in the demo and the tests."""


# ---------------------------------------------------------------------------
# Polls
# ---------------------------------------------------------------------------

def polls_open(election_id=ELECTION_ID):
    """No status row means the polls are open (the prototype's starting state)."""
    status = db.session.get(ElectionStatus, election_id)
    return status is None or status.polls_open


def close_polls(election_id=ELECTION_ID):
    """Stop accepting ballots. Returns False if the polls were already closed."""
    status = db.session.get(ElectionStatus, election_id)
    if status is not None and not status.polls_open:
        return False
    if status is None:
        status = ElectionStatus(election_id=election_id)
        db.session.add(status)
    status.polls_open = False
    status.closed_at = _now_iso()
    db.session.commit()
    record_event("POLLS_CLOSED", OFFICIAL, election_id=election_id)
    return True


# ---------------------------------------------------------------------------
# Checkpoints
# ---------------------------------------------------------------------------

def _sign(row):
    fields = [row.election_id, row.phase, row.ballots_counted,
              row.last_ballot_id, row.state_json, row.updated_at]
    message = json.dumps(fields, separators=(",", ":")).encode()
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def checkpoint_is_valid(row):
    """True if the checkpoint has not been changed since the count saved it."""
    return hmac.compare_digest((row.checkpoint_hmac or "").encode(), _sign(row).encode())


def _save(row, election_id, phase, counted, cursor, state):
    if row is None:
        row = CountCheckpoint(election_id=election_id)
        db.session.add(row)
    row.phase = phase
    row.ballots_counted = counted
    row.last_ballot_id = cursor
    row.state_json = json.dumps(state, sort_keys=True, separators=(",", ":"))
    row.updated_at = _now_iso()
    row.checkpoint_hmac = _sign(row)
    db.session.commit()  # totals and position are saved together, or not at all
    return row


def _discard(row):
    db.session.delete(row)
    db.session.commit()


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------

def _new_state():
    return {"house": {}, "senate": {}, "informal_house": 0,
            "informal_senate": 0, "result": None}


def _house_order(raw):
    """The ballot's House preferences, first to last, or None if not formal."""
    try:
        prefs = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(prefs, dict) or set(prefs) != set(HOUSE_CANDIDATES):
        return None
    result = validate_house_ballot(prefs)
    return result.order if result.valid else None


def _senate_first_group(raw):
    """The group given the Senate first preference, or None if not formal."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    method, prefs = data.get("method"), data.get("preferences")
    if method == "ATL":
        boxes, minimum = {group["code"] for group in SENATE_GROUPS}, SENATE_POLICY.atl_minimum
    elif method == "BTL":
        boxes, minimum = set(SENATE_CANDIDATE_GROUP), SENATE_POLICY.btl_minimum
    else:
        return None
    if not isinstance(prefs, dict) or not set(prefs) <= boxes:
        return None
    result = validate_senate_line(prefs, minimum, method)
    if not result.valid:
        return None
    first = result.order[0]
    return first if method == "ATL" else SENATE_CANDIDATE_GROUP[first]


def _tally(state, ballot):
    order = _house_order(ballot.house_prefs)
    if order is None:
        state["informal_house"] += 1
    else:
        key = ">".join(order)
        state["house"][key] = state["house"].get(key, 0) + 1
    group = _senate_first_group(ballot.senate_prefs)
    if group is None:
        state["informal_senate"] += 1
    else:
        state["senate"][group] = state["senate"].get(group, 0) + 1


def house_result(tally):
    """Full preferential count: exclude the lowest candidate until one has a majority."""
    ballots = [(key.split(">"), count) for key, count in tally.items()]
    formal = sum(count for _, count in ballots)
    if formal == 0:
        return {"formal_votes": 0, "rounds": [], "elected": None}
    continuing, rounds, first_round = list(HOUSE_CANDIDATES), [], None
    while True:
        votes = dict.fromkeys(continuing, 0)
        for order, count in ballots:
            votes[next(name for name in order if name in votes)] += count
        if first_round is None:
            first_round = dict(votes)
        leader = max(continuing, key=votes.get)
        if 2 * votes[leader] > formal or len(continuing) == 1:
            rounds.append({"votes": votes, "excluded": None})
            return {"formal_votes": formal, "rounds": rounds, "elected": leader}
        # Ties for last: fewer first preferences goes first, then the lower
        # position on the ballot paper. (A real count would draw lots.)
        lowest = min(continuing, key=lambda name: (
            votes[name], first_round[name], -HOUSE_CANDIDATES.index(name)))
        rounds.append({"votes": votes, "excluded": lowest})
        continuing.remove(lowest)


def run_count(election_id=ELECTION_ID, batch_size=100, crash_after=None,
              log=lambda message: None):
    """Count the election, resuming from a valid checkpoint if there is one."""
    if polls_open(election_id):
        raise CountError(
            "The polls are still open. Close them first: flask --app run close-polls")

    row = db.session.get(CountCheckpoint, election_id)
    if row is not None and not checkpoint_is_valid(row):
        _discard(row)
        row = None
        record_event("COUNT_CHECKPOINT_REJECTED", OFFICIAL, election_id=election_id)
        log("The saved checkpoint failed its integrity check and was discarded. "
            "Recounting from the first ballot.")
    if row is not None and row.phase == COMPLETE:
        log("The count is already complete.")
        return row

    if row is None:
        state, counted, cursor = _new_state(), 0, None
        record_event("COUNT_STARTED", OFFICIAL, election_id=election_id)
        log("Starting the count.")
    else:
        state = json.loads(row.state_json)
        counted, cursor = row.ballots_counted, row.last_ballot_id
        record_event("COUNT_RESUMED", OFFICIAL, election_id=election_id,
                     already_counted=counted)
        log(f"Resuming from the checkpoint: {counted} ballots already counted.")

    counted_this_run = 0
    while True:
        query = Ballot.query.filter(Ballot.election_id == election_id)
        if cursor is not None:
            query = query.filter(Ballot.ballot_id > cursor)
        batch = query.order_by(Ballot.ballot_id).limit(batch_size).all()
        if not batch:
            break
        for ballot in batch:
            _tally(state, ballot)
            counted, cursor = counted + 1, ballot.ballot_id
            counted_this_run += 1
            if crash_after is not None and counted_this_run >= crash_after:
                db.session.rollback()
                raise SimulatedCrash(
                    f"simulated crash after {counted_this_run} ballots. Anything counted "
                    "since the last checkpoint was lost; run the count again to resume.")
        row = _save(row, election_id, TALLYING, counted, cursor, state)
        log(f"Checkpoint saved: {counted} ballots counted.")

    stored = Ballot.query.filter_by(election_id=election_id).count()
    if stored != counted:
        if row is not None:
            _discard(row)
        record_event("COUNT_RECONCILIATION_FAILED", OFFICIAL,
                     election_id=election_id, counted=counted, stored=stored)
        raise CountError(
            f"{counted} ballots were counted but {stored} are stored, so this count "
            "was discarded. Run it again to recount from the start.")

    state["result"] = house_result(state["house"])
    row = _save(row, election_id, COMPLETE, counted, cursor, state)
    record_event("COUNT_COMPLETED", OFFICIAL, election_id=election_id, ballots=counted)
    log(f"Count complete: {counted} ballots counted.")
    return row


# ---------------------------------------------------------------------------
# Commands for election officials
# ---------------------------------------------------------------------------

def _echo_results(row):
    state = json.loads(row.state_json)
    house = state["result"]
    click.echo(f"\nBallots counted: {row.ballots_counted}")
    click.echo(f"House of Representatives: {house['formal_votes']} formal, "
               f"{state['informal_house']} informal")
    for number, rnd in enumerate(house["rounds"], start=1):
        totals = ", ".join(f"{name} {rnd['votes'][name]}"
                           for name in HOUSE_CANDIDATES if name in rnd["votes"])
        excluded = f"  ->  {rnd['excluded']} excluded" if rnd["excluded"] else ""
        click.echo(f"  Round {number}: {totals}{excluded}")
    click.echo(f"  Elected: {house['elected'] or 'nobody (no formal votes)'}")
    click.echo(f"Senate first preferences by group ({state['informal_senate']} informal):")
    for group in SENATE_GROUPS:
        click.echo(f"  {group['code']} {group['party']}: {state['senate'].get(group['code'], 0)}")


@click.command("close-polls")
@with_appcontext
def close_polls_command():
    """Req 19: stop accepting ballots so the count can start."""
    if close_polls():
        click.echo("Polls closed. No more ballots will be accepted.")
    else:
        click.echo("The polls were already closed.")


@click.command("count-votes")
@click.option("--batch-size", type=click.IntRange(min=1), default=100, show_default=True,
              help="Ballots counted between checkpoints.")
@click.option("--crash-after", type=click.IntRange(min=1), default=None,
              help="Demo only: stop abruptly after counting this many ballots.")
@with_appcontext
def count_votes_command(batch_size, crash_after):
    """Req 19: count the votes, resuming from the last checkpoint if there is one."""
    try:
        row = run_count(batch_size=batch_size, crash_after=crash_after, log=click.echo)
    except (CountError, SimulatedCrash) as exc:
        click.echo(f"Count stopped: {exc}")
        raise SystemExit(1)
    _echo_results(row)

import hashlib
import json
import secrets

from flask import (Blueprint, abort, current_app, jsonify, redirect,
                   render_template, request, session, url_for)
from sqlalchemy.exc import IntegrityError

from app import db
from app.auth.session_guard import active_user_id
from app.registration.models import VoterRecord
from app.voting.ballot_papers import (ELECTION_ID, HOUSE_CANDIDATES,
                                      SENATE_CANDIDATES, SENATE_GROUPS,
                                      SENATE_POLICY)
from app.voting.counting import COMPLETE, checkpoint_is_valid, polls_open
from app.voting.models import (Ballot, BallotToken, CountCheckpoint,
                               VoterParticipation)
from app.voting.validation import validate_house_ballot, validate_senate_ballot

voting_bp = Blueprint("voting", __name__)

BALLOT_FIELDS = ("pref_", "atl_", "btl_")


@voting_bp.before_request
def require_tls():
    """Req 6: refuse ballot traffic that did not arrive over HTTPS."""
    if current_app.config.get("REQUIRE_HTTPS") and not request.is_secure:
        abort(403)


@voting_bp.route("/ping")
def ping():
    return jsonify(blueprint="voting")


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _issue_token(voter):
    """Req 7: a one-time ballot token for this voter, or None if they have voted.

    The "has voted" record and the token are saved in one transaction. If the
    voter already has an unused token (e.g. they reloaded the page), it is
    replaced rather than added to, so they never hold more than one.
    """
    token = secrets.token_urlsafe(32)
    participation = VoterParticipation.query.filter_by(
        election_id=ELECTION_ID, voter_id=voter.voter_id
    ).first()

    if participation is None:
        db.session.add(VoterParticipation(
            election_id=ELECTION_ID,
            voter_id=voter.voter_id,
            token_hash=_hash(token),
        ))
    elif BallotToken.query.filter_by(token_hash=participation.token_hash).delete():
        participation.token_hash = _hash(token)
    else:
        db.session.rollback()  # their token has been used: they have voted
        return None

    db.session.add(BallotToken(token_hash=_hash(token), election_id=ELECTION_ID))
    try:
        db.session.commit()
    except IntegrityError:  # a simultaneous request recorded them first
        db.session.rollback()
        return None
    return token


def _show_ballot(token, values=None, errors=(), status=200):
    return render_template(
        "ballot.html", state="open", token=token, candidates=HOUSE_CANDIDATES,
        senate_groups=SENATE_GROUPS, policy=SENATE_POLICY,
        values=values or {}, errors=errors,
    ), status


@voting_bp.route("/ballot")
def ballot():
    user_id = active_user_id()  # Req 3
    if not user_id:
        return redirect(url_for("auth.login"))
    if not polls_open(ELECTION_ID):
        return render_template("ballot.html", state="closed")
    voter = VoterRecord.query.filter_by(user_id=user_id).first_or_404()

    token = _issue_token(voter)
    if token is None:
        return render_template("ballot.html", state="voted")
    return _show_ballot(token)


@voting_bp.route("/ballot", methods=["POST"])
def cast_ballot():
    """Store a ballot. Only the one-time token is used, never the voter's identity."""
    if not polls_open(ELECTION_ID):  # Req 19: no ballots once counting can start
        return render_template("ballot.html", state="closed"), 403

    form = request.form
    token = form.get("ballot_token", "")
    house = validate_house_ballot(
        {name: form.get(f"pref_{i}") for i, name in enumerate(HOUSE_CANDIDATES)})
    senate = validate_senate_ballot(
        {group["code"]: form.get(f"atl_{group['code']}") for group in SENATE_GROUPS},
        {candidate_id: form.get(f"btl_{candidate_id}") for candidate_id in SENATE_CANDIDATES},
        SENATE_POLICY,
    )

    # Req 17 and 18: the server decides whether a ballot is formal. Nothing is
    # used up until both papers pass, so the voter can correct and resubmit.
    errors = [result.message for result in (house, senate) if not result.valid]
    if errors:
        values = {key: value for key, value in form.items() if key.startswith(BALLOT_FIELDS)}
        return _show_ballot(token, values, errors, 400)

    # Req 7: using up the token and saving the ballot happen in one
    # transaction, so a replayed or simultaneous submission finds no token.
    used = BallotToken.query.filter_by(
        token_hash=_hash(token), election_id=ELECTION_ID
    ).delete()
    if not used:
        db.session.rollback()
        return render_template("ballot.html", state="used"), 409

    # Only formal preferences are stored; for the Senate, only the line that
    # counts (Req 18). The count checks them again (Req 19).
    db.session.add(Ballot(
        election_id=ELECTION_ID,
        house_prefs=json.dumps(_numbered(house.order)),
        senate_prefs=json.dumps(
            {"method": senate.method, "preferences": _numbered(senate.order)}),
    ))
    db.session.commit()
    return render_template("ballot.html", state="cast", senate_note=_senate_note(senate))


def _numbered(order):
    """("B", "A", "C") -> {"B": 1, "A": 2, "C": 3}"""
    return {key: number for number, key in enumerate(order, start=1)}


def _senate_note(result):
    if result.code.startswith("SENATE_DUAL"):
        return result.message
    line = "above the line" if result.method == "ATL" else "below the line"
    return f"Your Senate vote was recorded {line}."


@voting_bp.route("/results")
def results():
    """Req 19: results come only from a complete count whose checkpoint is intact."""
    row = db.session.get(CountCheckpoint, ELECTION_ID)
    if row is None or row.phase != COMPLETE:
        return render_template("results.html", status="pending")
    if not checkpoint_is_valid(row):
        return render_template("results.html", status="tampered")
    state = json.loads(row.state_json)
    senate = sorted(
        ((group["code"], group["party"], state["senate"].get(group["code"], 0))
         for group in SENATE_GROUPS),
        key=lambda item: -item[2],
    )
    return render_template(
        "results.html", status="final", ballots_counted=row.ballots_counted,
        house=state["result"], candidates=HOUSE_CANDIDATES, senate=senate,
        senate_formal=sum(state["senate"].values()),
        informal_house=state["informal_house"], informal_senate=state["informal_senate"],
    )

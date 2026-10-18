import hashlib
import json
import secrets
import time

from flask import (Blueprint, abort, current_app, jsonify, redirect,
                   render_template, request, session, url_for)
from sqlalchemy.exc import IntegrityError

from app import db
from app.registration.models import VoterRecord
from app.voting.models import Ballot, BallotToken, VoterParticipation

voting_bp = Blueprint("voting", __name__)

ELECTION_ID = "FED2026"  # the prototype runs a single election
HOUSE_CANDIDATES = ["Avery Brooks", "Jordan Lee", "Priya Nair", "Sam Walker"]
SESSION_TIMEOUT_SECONDS = 60  # same idle limit as auth.home (Req 3)


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


@voting_bp.route("/ballot")
def ballot():
    user_id = session.get("authenticated_user_id")
    if not user_id or time.time() - session.get("last_activity", 0) >= SESSION_TIMEOUT_SECONDS:
        session.clear()
        return redirect(url_for("auth.login"))
    voter = VoterRecord.query.filter_by(user_id=user_id).first_or_404()

    token = _issue_token(voter)
    if token is None:
        return render_template("ballot.html", state="voted")
    return render_template(
        "ballot.html", state="open", token=token, candidates=HOUSE_CANDIDATES
    )


@voting_bp.route("/ballot", methods=["POST"])
def cast_ballot():
    """Store a ballot. Only the one-time token is used, never the voter's identity."""
    token = request.form.get("ballot_token", "")
    try:
        prefs = {
            name: int(request.form[f"pref_{i}"])
            for i, name in enumerate(HOUSE_CANDIDATES)
        }
    except (KeyError, ValueError):
        return render_template(
            "ballot.html", state="open", token=token, candidates=HOUSE_CANDIDATES,
            message="Enter a number for every candidate.",
        ), 400
    # Formal checks on the numbering (an unbroken 1..N sequence) are Req 17.

    # Req 7: using up the token and saving the ballot happen in one
    # transaction, so a replayed or simultaneous submission finds no token.
    used = BallotToken.query.filter_by(
        token_hash=_hash(token), election_id=ELECTION_ID
    ).delete()
    if not used:
        db.session.rollback()
        return render_template("ballot.html", state="used"), 409

    db.session.add(Ballot(election_id=ELECTION_ID, house_prefs=json.dumps(prefs)))
    db.session.commit()
    return render_template("ballot.html", state="cast")

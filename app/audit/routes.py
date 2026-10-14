import time
from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    session,
    url_for,
)
from app.audit.models import RegistrationChange
from app.registration.models import VoterRecord

audit_bp = Blueprint("audit", __name__)

@audit_bp.route("/ping")
def ping():
    return jsonify(blueprint="audit")

@audit_bp.route("/registration-history")
def registration_history():
    user_id = session.get("authenticated_user_id")
    last_activity = session.get("last_activity", 0)

    # Require an authenticated session.
    if not user_id:
        session.clear()
        return redirect(url_for("auth.login"))

    # Apply the existing inactivity timeout.
    if time.time() - last_activity >= 10:
        session.clear()
        return redirect(url_for("auth.login"))

    # Find the registration record belonging to the signed-in voter.
    voter = VoterRecord.query.filter_by(user_id=user_id).first()

    if voter is None:
        return "Voter registration record not found.", 404

    # Retrieve only this voter's registration change history,
    # with the most recent change displayed first.
    changes = (
        RegistrationChange.query
        .filter_by(user_id=user_id)
        .order_by(RegistrationChange.changed_at.desc())
        .all()
    )

    return render_template(
        "registration_history.html",
        voter=voter,
        changes=changes,
    )

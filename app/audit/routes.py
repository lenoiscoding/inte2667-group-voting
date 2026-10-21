from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    session,
    url_for,
)
from app.audit.models import RegistrationChange
from app.auth.session_guard import active_user_id
from app.registration.models import VoterRecord

audit_bp = Blueprint("audit", __name__)

@audit_bp.route("/ping")
def ping():
    return jsonify(blueprint="audit")

@audit_bp.route("/registration-history")
def registration_history():
    # Req 3: logged in and not idle for too long.
    user_id = active_user_id()
    if not user_id:
        return redirect(url_for("auth.login"))

    voter = VoterRecord.query.filter_by(user_id=user_id).first()

    if voter is None:
        return "Voter registration record not found.", 404

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

from app.email_service import send_registration_change_email
from datetime import date, datetime
from io import BytesIO
import base64
import pyotp
import qrcode
import time
from flask import (Blueprint,jsonify,render_template,request,session,redirect,url_for,)
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash
from app.audit.models import RegistrationChange
from app import db
from app.auth.models.user import User
from app.registration.models import VoterRecord

registration_bp = Blueprint("registration", __name__)

MIN_AGE = 18
MIN_PASSWORD_LENGTH = 12


def _age(dob):
    today = date.today()
    return today.year - dob.year - (
        (today.month, today.day) < (dob.month, dob.day)
    )

def _generate_qr(secret, username):
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name="Election System"
    )

    buffer = BytesIO()
    qrcode.make(uri).save(buffer, format="PNG")

    return base64.b64encode(buffer.getvalue()).decode("utf-8")


@registration_bp.route("/ping")
def ping():
    return jsonify(blueprint="registration")


@registration_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", message="", success=False, qr_code=None)

    username = (request.form.get("username") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    full_name = (request.form.get("full_name") or "").strip()
    address = (request.form.get("address") or "").strip()
    id_document_number = (
        request.form.get("id_document_number") or ""
    ).strip().upper()
    dob_raw = request.form.get("date_of_birth") or ""

    def fail(message, status=400):
        return render_template(
            "register.html", message=message, success=False, qr_code=None
        ), status

    if not all([
        username,
        email,
        password,
        full_name,
        address,
        id_document_number,
        dob_raw,
    ]):
        return fail("All fields are required.")

    if (
        len(email) > 254
        or email.count("@") != 1
        or email.startswith("@")
        or email.endswith("@")
        or "." not in email.rsplit("@", 1)[1]
    ):
        return fail("Please enter a valid email address.")
    if len(password) < MIN_PASSWORD_LENGTH:
        return fail(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )

    try:
        dob = datetime.strptime(dob_raw, "%Y-%m-%d").date()
    except ValueError:
        return fail("Invalid date of birth.")

    if _age(dob) < MIN_AGE:
        return fail(f"You must be at least {MIN_AGE} to register.")

    # Duplicate registration check
    already_registered = (
        User.query.filter_by(username=username).first()
        or User.query.filter_by(email=email).first()
        or VoterRecord.query.filter_by(
            id_document_number=id_document_number
        ).first()
    )
    if already_registered:
        return fail("These details are already registered.", 409)

    secret = pyotp.random_base32()

    try:
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role="voter",
            totp_secret=secret
        )
        db.session.add(user)
        db.session.flush()

        voter = VoterRecord(
            user_id=user.user_id,
            full_name=full_name,
            date_of_birth=dob,
            address=address,
            id_document_number=id_document_number
        )
        db.session.add(voter)
        db.session.commit()
        voter_ref = voter.voter_ref
        qr_code = _generate_qr(secret, username)
    except IntegrityError:
        db.session.rollback()
        return fail("These details are already registered.", 409)

    return render_template(
        "register.html",
        message=(
            f"Registration successful. Your voter reference is "
            f"{voter_ref}. Scan the QR code with Google Authenticator."
        ),
        success=True,
        qr_code=qr_code
    ), 201


@registration_bp.route("/update-details", methods=["GET", "POST"])
def update_details():
    user_id = session.get("authenticated_user_id")
    last_activity = session.get("last_activity", 0)

    # Require an authenticated session.
    if not user_id:
        session.clear()
        return redirect(url_for("auth.login"))

    # Enforce the existing inactivity timeout.
    if time.time() - last_activity >= 10:
        session.clear()
        return redirect(url_for("auth.login"))

    voter = VoterRecord.query.filter_by(user_id=user_id).first()

    if voter is None:
        return "Voter registration record not found.", 404

    if request.method == "GET":
        return render_template(
            "update_registration.html",
            voter=voter,
            message="",
        )

    full_name = (request.form.get("full_name") or "").strip()
    address = (request.form.get("address") or "").strip()

    if not full_name or not address:
        return render_template(
            "update_registration.html",
            voter=voter,
            message="Name and address are required.",
        ), 400

    if len(full_name) > 150 or len(address) > 255:
        return render_template(
            "update_registration.html",
            voter=voter,
            message="Name or address exceeds the permitted length.",
        ), 400

    changes = []

    if full_name != voter.full_name:
        changes.append(
            RegistrationChange(
                user_id=user_id,
                field_name="full_name",
                old_value=voter.full_name,
                new_value=full_name,
            )
        )

    if address != voter.address:
        changes.append(
            RegistrationChange(
                user_id=user_id,
                field_name="address",
                old_value=voter.address,
                new_value=address,
            )
        )
    changed_fields = [
        change.field_name for change in changes
    ]

    try:
        if full_name != voter.full_name:
            voter.full_name = full_name

        if address != voter.address:
            voter.address = address

        db.session.add_all(changes)
        db.session.commit()

    except Exception:
        db.session.rollback()
        raise

    notification_message = ""

    if changes:
        user = db.session.get(User, user_id)

        if user and user.email:
            try:
                send_registration_change_email(
                    user.email,
                    changed_fields
                )
                notification_message = (
                    " An email notification was sent."
                )
            except Exception:
                # The database changes are already committed.
                # Do not undo them if email delivery fails.
                notification_message = (
                    " However, the email notification could not "
                    "be sent. Please contact the system "
                    "administrator."
                )
        else:
            notification_message = (
                " No email notification was sent because "
                "your account has no email address."
            )

    return render_template(
        "update_registration.html",
        voter=voter,
        message=(
            (
                "Registration details updated successfully."
                + notification_message
            )
            if changes
            else "No changes were made to your registration details."
        ),
    )

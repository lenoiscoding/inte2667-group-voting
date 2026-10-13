from datetime import date, datetime
from io import BytesIO
import base64
import pyotp
import qrcode
from flask import Blueprint, jsonify, render_template, request
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

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

    if not all([username, password, full_name, address, id_document_number, dob_raw]):
        return fail("All fields are required.")

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

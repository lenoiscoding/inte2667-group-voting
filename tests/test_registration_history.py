import time
from datetime import date, datetime, timezone

from werkzeug.security import generate_password_hash

from app import create_app, db
from app.auth.models.user import User
from app.registration.models import VoterRecord
from app.audit.models import RegistrationChange


def test_registration_history_is_limited_to_authenticated_voter(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "test_registration_history.db"
    monkeypatch.setenv(
        "DATABASE_URL", f"sqlite:///{database_path.as_posix()}"
    )

    app = create_app()
    app.config["TESTING"] = True

    with app.app_context():
        db.drop_all()
        db.create_all()

        voter1 = User(
            username="r15_voter_one",
            password_hash=generate_password_hash("TestPassword123!"),
            role="voter",
            is_active=True,
        )
        voter2 = User(
            username="r15_voter_two",
            password_hash=generate_password_hash("TestPassword123!"),
            role="voter",
            is_active=True,
        )
        db.session.add_all([voter1, voter2])
        db.session.flush()

        voter1_id = voter1.user_id
        voter2_id = voter2.user_id

        record1 = VoterRecord(
            user_id=voter1_id,
            full_name="Voter One",
            date_of_birth=date(2000, 1, 1),
            address="10 Test Street",
            id_document_number="R15-TEST-001",
        )
        record2 = VoterRecord(
            user_id=voter2_id,
            full_name="Voter Two",
            date_of_birth=date(2001, 2, 2),
            address="20 Example Street",
            id_document_number="R15-TEST-002",
        )

        change1 = RegistrationChange(
            user_id=voter1_id,
            field_name="address",
            old_value="Old One Street",
            new_value="10 Test Street",
            changed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        change2 = RegistrationChange(
            user_id=voter2_id,
            field_name="address",
            old_value="Old Two Street",
            new_value="20 Example Street",
            changed_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

        db.session.add_all([record1, record2, change1, change2])
        db.session.commit()

    client = app.test_client()

    with client.session_transaction() as session:
        session["authenticated_user_id"] = voter1_id
        session["last_activity"] = time.time()

    response = client.get("/api/audit/registration-history")

    assert response.status_code == 200
    assert b"Old One Street" in response.data
    assert b"10 Test Street" in response.data
    assert b"Old Two Street" not in response.data
    assert b"20 Example Street" not in response.data

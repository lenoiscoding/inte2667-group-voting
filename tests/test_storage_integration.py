"""Req 8, 9 and 11: Don's storage module working inside the app."""
import os

import pyotp
import pytest
from cryptography.exceptions import InvalidTag
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from app import create_app, db
from app.registration.models import VoterRecord
from app.storage.integration import AuditLog, verify_chain
from app.storage.storage import restore_snapshot, write_encrypted_snapshot

VOTER = {
    "username": "alice", "email": "alice@example.com", "password": "CorrectHorse12",
    "full_name": "Alice Smith", "address": "1 Test St", "id_document_number": "AB123",
    "date_of_birth": "1990-01-01",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")  # fresh in-memory database
    app = create_app()
    with app.app_context():
        yield app.test_client()
        db.session.remove()


def register_and_log_in(client):
    client.post("/registration/register", data=VOTER)
    secret = db.session.execute(text("SELECT totp_secret FROM users")).scalar()
    client.post("/auth/login", data={"username": "alice", "password": VOTER["password"]})
    client.post("/auth/login", data={"otp": pyotp.TOTP(secret).now()})


def test_voter_details_are_encrypted_at_rest(client):
    client.post("/registration/register", data=VOTER)

    stored = db.session.execute(
        text("SELECT full_name, address, date_of_birth FROM voter_records")).one()
    for column, plaintext in zip(stored, ("Alice Smith", "1 Test St", "1990-01-01")):
        assert plaintext not in column

    voter = VoterRecord.query.one()  # the app still sees plaintext
    assert (voter.full_name, voter.address, str(voter.date_of_birth)) == (
        "Alice Smith", "1 Test St", "1990-01-01")


def test_change_history_is_encrypted_at_rest(client):
    register_and_log_in(client)
    client.post("/registration/update-details",
                data={"full_name": "Alice Jones", "address": "2 New St"})

    stored = db.session.execute(
        text("SELECT old_value, new_value FROM registration_changes")).all()
    assert len(stored) == 2
    for value in (v for row in stored for v in row):
        assert all(p not in value for p in ("Alice Smith", "Alice Jones", "1 Test St", "2 New St"))

    page = client.get("/api/audit/registration-history").get_data(as_text=True)
    assert "Alice Smith" in page and "Alice Jones" in page


def test_logins_and_registration_are_hash_chained(client):
    register_and_log_in(client)
    client.post("/auth/login", data={"username": "alice", "password": "wrong-password"})
    client.post("/auth/login", data={"username": "nobody", "password": "x"})

    entries = AuditLog.query.order_by(AuditLog.entry_id).all()
    assert [e.event_type for e in entries] == [
        "VOTER_REGISTERED", "LOGIN_SUCCESS", "LOGIN_FAILED", "LOGIN_FAILED"]
    assert all(later.prev_hash == earlier.row_hash for earlier, later in zip(entries, entries[1:]))
    assert verify_chain() == (True, "OK")


def test_audit_log_is_append_only(client):
    client.post("/registration/register", data=VOTER)
    for sql in ("UPDATE audit_log SET actor_id = 'someone-else'", "DELETE FROM audit_log"):
        with pytest.raises(DatabaseError):
            db.session.execute(text(sql))
        db.session.rollback()
    assert AuditLog.query.count() == 1


def test_tampering_is_detected(client):
    register_and_log_in(client)
    # Someone with full control of the database removes the guard and edits a row.
    db.session.execute(text("DROP TRIGGER audit_log_no_update"))
    db.session.execute(text("UPDATE audit_log SET actor_id = '999' WHERE entry_id = 1"))
    db.session.commit()

    ok, message = verify_chain()
    assert not ok and "entry_id=1" in message


def test_backups_use_the_aes_key_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("AES_KEY", os.urandom(32).hex())
    snapshot = write_encrypted_snapshot(b"-- pg_dump output --", str(tmp_path))

    restored = tmp_path / "restored.sql"
    restore_snapshot(snapshot["snapshot_file"], str(restored))
    assert restored.read_bytes() == b"-- pg_dump output --"

    monkeypatch.delenv("AES_KEY")  # the built-in test key must not open it
    with pytest.raises(InvalidTag):
        restore_snapshot(snapshot["snapshot_file"], str(restored))

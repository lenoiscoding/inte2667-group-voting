import pytest

from app import create_app, db
from app.auth.models.user import User
from app.registration.models import VoterRecord

VALID = {
    "full_name": "Test Voter",
    "date_of_birth": "1990-05-17",
    "address": "1 Example St, Melbourne VIC 3000",
    "id_document_number": "ID123456",
    "username": "voter1",
    "password": "a-long-enough-password",
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    app = create_app()
    with app.app_context():
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def test_register_page_loads(client):
    assert client.get("/registration/register").status_code == 200


def test_register_creates_user_and_record(client):
    resp = client.post("/registration/register", data=VALID)
    assert resp.status_code == 201

    user = User.query.filter_by(username="voter1").first()
    assert user is not None
    assert user.role == "voter"
    assert user.password_hash != VALID["password"]
    assert VoterRecord.query.filter_by(user_id=user.user_id).count() == 1


def test_duplicate_id_document_number_rejected(client):
    client.post("/registration/register", data=VALID)
    second = {**VALID, "username": "voter2"}
    assert client.post("/registration/register", data=second).status_code == 409
    assert User.query.count() == 1


def test_duplicate_username_rejected(client):
    client.post("/registration/register", data=VALID)
    second = {**VALID, "id_document_number": "ID999999"}
    assert client.post("/registration/register", data=second).status_code == 409


def test_underage_rejected(client):
    data = {**VALID, "date_of_birth": "2015-01-01"}
    assert client.post("/registration/register", data=data).status_code == 400
    assert User.query.count() == 0


def test_short_password_rejected(client):
    data = {**VALID, "password": "short"}
    assert client.post("/registration/register", data=data).status_code == 400


def test_missing_field_rejected(client):
    data = {k: v for k, v in VALID.items() if k != "address"}
    assert client.post("/registration/register", data=data).status_code == 400


def test_voter_ref_is_generated_and_random(client):
    client.post("/registration/register", data=VALID)
    second = {**VALID, "username": "voter2", "id_document_number": "ID777777"}
    client.post("/registration/register", data=second)

    refs = [v.voter_ref for v in VoterRecord.query.all()]
    assert len(refs) == 2
    assert refs[0] != refs[1]
    assert all(r.startswith("V") and len(r) == 17 for r in refs)


def test_voter_cannot_choose_own_voter_ref(client):
    data = {**VALID, "voter_ref": "VCHOSENBYUSER0000"}
    client.post("/registration/register", data=data)
    assert VoterRecord.query.first().voter_ref != "VCHOSENBYUSER0000"

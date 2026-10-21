"""Req 20: only people on the electoral roll can register."""
from datetime import date

import pytest
from sqlalchemy import text

from app import db
from app.auth.models.user import User
from app.registration.eligibility import is_eligible
from app.registration.models import ElectoralRollEntry
from app.storage.integration import AuditLog

FORM = {
    "username": "casey", "email": "casey@example.com", "password": "CorrectHorse12",
    "full_name": "Casey Jordan", "address": "5 Roll St", "id_document_number": "pa4567890",
    "date_of_birth": "1978-02-14",
}
HEADER = "id_document_number,full_name,date_of_birth,eligible\n"


@pytest.fixture
def roll(app):
    db.session.add_all([
        ElectoralRollEntry(id_document_number="PA4567890", full_name="Casey Jordan",
                           date_of_birth=date(1978, 2, 14)),
        ElectoralRollEntry(id_document_number="PA6789012", full_name="Morgan Lee",
                           date_of_birth=date(1969, 12, 1), is_eligible=False),
    ])
    db.session.commit()


def register(client, **changes):
    return client.post("/registration/register", data={**FORM, **changes})


def test_person_on_the_roll_can_register(client, roll):
    assert register(client).status_code == 201  # ID typed in lower case still matches
    assert User.query.count() == 1


@pytest.mark.parametrize("changes", [
    {"id_document_number": "PA0000000"},  # not on the roll
    {"date_of_birth": "1978-02-15"},  # wrong date of birth
    {"full_name": "Casey Jordon"},  # wrong name
    {"id_document_number": "PA6789012", "full_name": "Morgan Lee",
     "date_of_birth": "1969-12-01"},  # on the roll but not eligible
])
def test_person_not_matching_the_roll_cannot_register(client, roll, changes):
    response = register(client, **changes)
    assert response.status_code == 403
    assert "electoral roll" in response.get_data(as_text=True)
    assert User.query.count() == 0
    assert AuditLog.query.filter_by(event_type="ELIGIBILITY_CHECK_FAILED").count() == 1


def test_name_check_ignores_case_and_extra_spaces(roll):
    assert is_eligible(" pa4567890 ", "  casey   JORDAN ", date(1978, 2, 14))


def test_check_fails_closed_when_the_roll_is_unavailable(roll):
    class UnavailableRoll:
        def lookup(self, id_number):
            raise ConnectionError("enrolment service down")

    assert not is_eligible("PA4567890", "Casey Jordan", date(1978, 2, 14), roll=UnavailableRoll())


def test_import_roll_adds_then_updates_and_encrypts(app, tmp_path):
    roll_file = tmp_path / "roll.csv"
    roll_file.write_text(HEADER + "PA1,Alex Morgan,1990-04-12,yes\nPA2,Jamie Taylor,1985-11-03,no\n")
    runner = app.test_cli_runner()
    assert "2 added, 0 updated" in runner.invoke(args=["import-roll", str(roll_file)]).output
    assert "0 added, 2 updated" in runner.invoke(args=["import-roll", str(roll_file)]).output
    assert is_eligible("PA1", "Alex Morgan", date(1990, 4, 12))
    assert not is_eligible("PA2", "Jamie Taylor", date(1985, 11, 3))
    stored = db.session.execute(text("SELECT full_name FROM electoral_roll")).scalars().all()
    assert "Alex Morgan" not in stored  # Req 8: encrypted at rest


def test_import_roll_rejects_a_bad_file_and_imports_nothing(app, tmp_path):
    roll_file = tmp_path / "roll.csv"
    roll_file.write_text(HEADER + "PA1,Alex Morgan,1990-04-12,yes\nPA2,Jamie Taylor,03/11/1985,yes\n")
    result = app.test_cli_runner().invoke(args=["import-roll", str(roll_file)])
    assert result.exit_code != 0 and "Line 3" in result.output
    assert ElectoralRollEntry.query.count() == 0

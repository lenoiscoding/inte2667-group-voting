"""Req 20: only people on the electoral roll can register.

The prototype checks a local copy of the roll (the option chosen in the
report). In production the copy would be replaced by a call to the official
enrolment service, and only LocalElectoralRoll would change. Adapted from
Sahil's VoterEligibilityService (requirements_17-20.py).

The check fails closed: if the roll cannot be read, nobody is let through.
"""
import csv
from datetime import datetime

import click
from flask.cli import with_appcontext

from app import db
from app.registration.models import ElectoralRollEntry
from app.storage.integration import record_event

ROLL_COLUMNS = ["id_document_number", "full_name", "date_of_birth", "eligible"]


def clean_id_number(value):
    """The same clean-up the registration form applies (trim, upper-case)."""
    return (value or "").strip().upper()


def _same_name(first, second):
    return " ".join(first.split()).casefold() == " ".join(second.split()).casefold()


class LocalElectoralRoll:
    """The local copy of the roll, kept in the app's database."""

    def lookup(self, id_document_number):
        return ElectoralRollEntry.query.filter_by(
            id_document_number=id_document_number).first()


def is_eligible(id_document_number, full_name, date_of_birth, roll=None):
    """True only if an eligible roll entry matches the ID number, name and date of birth."""
    roll = roll or LocalElectoralRoll()
    try:
        entry = roll.lookup(clean_id_number(id_document_number))
    except Exception:  # fail closed: a roll that cannot be read approves nobody
        db.session.rollback()
        return False
    return (
        entry is not None
        and entry.is_eligible
        and entry.date_of_birth == date_of_birth
        and _same_name(entry.full_name, full_name)
    )


def _read_roll(path):
    """Check the whole file first, so a bad row means nothing is imported."""
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ROLL_COLUMNS:
            raise click.ClickException("The CSV header must be: " + ",".join(ROLL_COLUMNS))
        for line, record in enumerate(reader, start=2):
            id_number = clean_id_number(record["id_document_number"])
            name = " ".join((record["full_name"] or "").split())
            eligible = (record["eligible"] or "").strip().lower()
            try:
                dob = datetime.strptime((record["date_of_birth"] or "").strip(), "%Y-%m-%d").date()
            except ValueError:
                raise click.ClickException(f"Line {line}: date_of_birth must be YYYY-MM-DD.")
            if not id_number or len(id_number) > 50 or not name or eligible not in ("yes", "no"):
                raise click.ClickException(
                    f"Line {line}: needs an ID number, a full name and eligible yes/no.")
            if id_number in seen:
                raise click.ClickException(f"Line {line}: ID number {id_number} appears twice.")
            seen.add(id_number)
            rows.append((id_number, name, dob, eligible == "yes"))
    return rows


@click.command("import-roll")
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@with_appcontext
def import_roll_command(csv_path):
    """Req 20: load or refresh the local copy of the electoral roll from a CSV file.

    Columns: id_document_number, full_name, date_of_birth (YYYY-MM-DD), eligible (yes/no).
    """
    added = updated = 0
    for id_number, name, dob, eligible in _read_roll(csv_path):
        entry = ElectoralRollEntry.query.filter_by(id_document_number=id_number).first()
        if entry is None:
            entry = ElectoralRollEntry(id_document_number=id_number)
            db.session.add(entry)
            added += 1
        else:
            updated += 1
        entry.full_name, entry.date_of_birth, entry.is_eligible = name, dob, eligible
    db.session.commit()
    record_event("ROLL_IMPORTED", "election-official", added=added, updated=updated)
    click.echo(f"Electoral roll loaded: {added} added, {updated} updated.")

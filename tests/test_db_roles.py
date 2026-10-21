"""Req 21: the web app's database role gets only the privileges it needs."""
from app import db
from app.security.db_roles import APP_PRIVILEGES


def test_every_table_has_a_privilege_entry(app):
    # A table missing here would get no access at all, so a new table must be listed.
    assert set(APP_PRIVILEGES) == set(db.metadata.tables)


def test_logs_are_append_only_and_ballots_write_only():
    for table in ("audit_log", "login_attempts", "registration_changes"):
        assert "UPDATE" not in APP_PRIVILEGES[table] and "DELETE" not in APP_PRIVILEGES[table]
    assert APP_PRIVILEGES["ballots"] == "INSERT"  # cannot read, change or delete ballots
    for table in ("electoral_roll", "election_status", "count_checkpoints"):
        assert APP_PRIVILEGES[table] == "SELECT"  # only election officials change these


def test_init_db_on_sqlite_only_creates_tables(app):
    result = app.test_cli_runner().invoke(args=["init-db"])
    assert result.exit_code == 0 and "only apply to PostgreSQL" in result.output

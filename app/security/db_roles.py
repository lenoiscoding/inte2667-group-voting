"""Req 21: the web app connects to PostgreSQL as a least-privilege role.

Two database roles:
  evoting      the owner of the tables (the admin role). Used only by
               short-lived admin containers: creating tables, backups and the
               election officials' commands (import-roll, close-polls,
               count-votes). The long-running web app never has its password.
  evoting_app  the web app's login. It gets only the privileges in
               APP_PRIVILEGES, so even if the app is compromised (for example
               by SQL injection), the database itself refuses anything else.

`flask --app run init-db` runs as evoting in the `admin` service on every
`docker compose up`: it creates any missing tables, then re-applies the grants.
"""
import os

import click
from flask.cli import with_appcontext

from app import db

APP_ROLE = "evoting_app"

# What the web app may do with each table. A table not listed gets no access.
APP_PRIVILEGES = {
    "users": "SELECT, INSERT, UPDATE",
    "voter_records": "SELECT, INSERT, UPDATE",
    "voter_participation": "SELECT, INSERT, UPDATE",
    "ballot_tokens": "SELECT, INSERT, DELETE",
    # Append-only: rows can be added but never changed or removed.
    "login_attempts": "SELECT, INSERT",  # Req 4
    "audit_log": "SELECT, INSERT",  # Req 9
    "registration_changes": "SELECT, INSERT",  # Req 15
    # Write-only: the app can cast a ballot but cannot read, change or delete one (Req 10).
    "ballots": "INSERT",
    # Read-only: only election officials change these (Req 19, 20).
    "electoral_roll": "SELECT",
    "election_status": "SELECT",
    "count_checkpoints": "SELECT",
}


def apply_grants(app_password):
    """Create or update evoting_app and give it exactly APP_PRIVILEGES. Run as the owner."""
    from psycopg2 import sql  # PostgreSQL only

    role = sql.Identifier(APP_ROLE)
    connection = db.engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_ROLE,))
            verb = "ALTER" if cursor.fetchone() else "CREATE"
            cursor.execute(sql.SQL(
                verb + " ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
            ).format(role, sql.Literal(app_password)))
            # Nobody but the owner can create tables (the PostgreSQL 15+ default, made explicit).
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            # Start from nothing, then grant table by table, all in one transaction.
            cursor.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(role))
            for table, privileges in APP_PRIVILEGES.items():
                cursor.execute(sql.SQL("GRANT " + privileges + " ON {} TO {}").format(
                    sql.Identifier(table), role))
            # Lets INSERT take the next ID from the tables' sequences.
            cursor.execute(sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {}").format(role))
        connection.commit()
    finally:
        connection.close()


@click.command("init-db")
@with_appcontext
def init_db_command():
    """Req 21: create missing tables and give the web app's role only what it needs."""
    db.create_all()
    if db.engine.dialect.name != "postgresql":
        click.echo("Tables are ready. Database roles only apply to PostgreSQL.")
        return
    password = os.environ.get("APP_DB_PASSWORD")
    if not password:
        raise click.ClickException("Set APP_DB_PASSWORD, the web app's database password.")
    apply_grants(password)
    click.echo(f"Tables are ready and {APP_ROLE} has least-privilege access.")

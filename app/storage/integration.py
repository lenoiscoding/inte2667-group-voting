"""
integration.py - connects storage.py (Req 8-11) to the Flask app's database.

  Req 8  - EncryptedText / EncryptedDate: model columns that storage.PIIEncryption
           encrypts (AES-256-GCM) before they reach the database.
  Req 9  - AuditLog: the hash-chained audit table, in the app's database. Rows are
           hashed with storage._compute_row_hash and checked with
           storage.verify_audit_chain. A trigger makes the table append-only.
  Req 10 - already met by the voting tables (app/voting/models.py).
  Req 11 - see backup.py.

Votes are never written to the audit log: a timestamped "voter X voted" entry
would make it easier to match voters to the anonymous ballots.
"""
import json
from datetime import date
from functools import lru_cache

import click
from flask.cli import with_appcontext
from sqlalchemy import DDL, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.types import Text, TypeDecorator

from app import db
from app.storage.storage import (
    PIIEncryption,
    _compute_row_hash,
    _now_iso,
    verify_audit_chain,
)


# ===========================================================================
# Req 8 - encrypted columns
# ===========================================================================

@lru_cache(maxsize=1)
def _pii():
    return PIIEncryption()  # key from AES_KEY (the test key if it is unset)


class EncryptedText(TypeDecorator):
    """Stored as AES-256-GCM ciphertext; the app only ever sees plaintext."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else _pii()._encrypt_field(str(value))

    def process_result_value(self, value, dialect):
        return None if value is None else _pii()._decrypt_field(value)


class EncryptedDate(EncryptedText):
    """A date, encrypted as its ISO text (YYYY-MM-DD)."""

    def process_bind_param(self, value, dialect):
        return super().process_bind_param(value and value.isoformat(), dialect)

    def process_result_value(self, value, dialect):
        value = super().process_result_value(value, dialect)
        return None if value is None else date.fromisoformat(value)


# ===========================================================================
# Req 9 - hash-chained audit log
# ===========================================================================

class AuditLog(db.Model):
    """Same columns as storage.init_audit_table."""

    __tablename__ = "audit_log"

    entry_id = db.Column(db.Integer, primary_key=True, autoincrement=False)
    event_type = db.Column(db.String(50), nullable=False)
    actor_id = db.Column(db.String(100), nullable=False)
    detail = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.String(32), nullable=False)  # text, so it hashes the same on every database
    row_hash = db.Column(db.String(64), nullable=False)
    prev_hash = db.Column(db.String(64))


# Append-only at the database level: UPDATE and DELETE are refused even if
# they bypass the app. A database superuser could still drop the trigger;
# the hash chain would then show the change, and Req 21's roles stop that.
event.listen(AuditLog.__table__, "after_create", DDL("""
CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE OR TRUNCATE
ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();
""").execute_if(dialect="postgresql"))

for _op in ("UPDATE", "DELETE"):
    event.listen(AuditLog.__table__, "after_create", DDL(
        f"CREATE TRIGGER audit_log_no_{_op.lower()} BEFORE {_op} ON audit_log "
        "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END"
    ).execute_if(dialect="sqlite"))


def record_event(event_type, actor_id, **detail):
    """Append one event to the chain. Call it after the action is committed.

    entry_id is the previous entry's id + 1 and is the primary key, so if two
    requests append at the same moment, one gets an IntegrityError instead of
    forking the chain, and retries on top of the new last entry.
    """
    actor_id, detail = str(actor_id), json.dumps(detail, sort_keys=True)
    for _ in range(5):
        tip = AuditLog.query.order_by(AuditLog.entry_id.desc()).first()
        entry_id = tip.entry_id + 1 if tip else 1
        prev_hash = tip.row_hash if tip else None
        timestamp = _now_iso()
        db.session.add(AuditLog(
            entry_id=entry_id, event_type=event_type, actor_id=actor_id,
            detail=detail, timestamp=timestamp, prev_hash=prev_hash,
            row_hash=_compute_row_hash(entry_id, event_type, actor_id,
                                       detail, timestamp, prev_hash),
        ))
        try:
            db.session.commit()
            return
        except IntegrityError:
            db.session.rollback()
    raise RuntimeError("Could not append to the audit log.")


class _SessionConnection:
    """Lets storage.verify_audit_chain() (written for sqlite3) read this database."""

    def execute(self, sql):
        return db.session.execute(text(sql))


def verify_chain():
    """Re-check every hash in the audit log. Returns (ok, message)."""
    return verify_audit_chain(_SessionConnection())


@click.command("verify-audit")
@with_appcontext
def verify_audit_command():
    """Req 9: check the audit log's hash chain."""
    ok, message = verify_chain()
    click.echo(message)
    if not ok:
        raise SystemExit(1)

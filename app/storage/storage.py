"""
storage.py - storage part of our A3 voting system (Part 3)
s4129654 - Don Carlos Porte

This file has my 4 storage requirements:
  Req 8  - encrypt voter details (name, address, DOB) with AES-256-GCM
  Req 9  - audit log that uses hash chaining so you can tell if someone edits it
  Req 10 - ballots are stored separately so they can't be traced back to a voter
  Req 11 - encrypted backups of the database with a SHA-256 checksum

I used SQLite here so it's easy to run and test without setting up Postgres.
"""

import os
import json
import hashlib
import sqlite3
import tempfile
import datetime
from base64 import b64encode, b64decode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ---- helpers ----

def _now_iso() -> str:
    # current UTC time as a string, used for created_at and the audit log
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ===========================================================================
# Req 8 - encrypting voter personal info
# ===========================================================================

class PIIEncryption:
    """
    Encrypts the voter's name, address and DOB before they go into the db.

    I went with AES-GCM (option B in our Part 2) because it does encryption
    and tamper checking together - if someone changes the stored value,
    decrypt just fails. Each field is encrypted on its own.

    The key needs to be 32 bytes (256 bits). It comes from the AES_KEY env
    variable (as hex). If that's not set it uses a fixed test key, which is
    fine for the prototype but obviously not for a real election.
    """

    def __init__(self, hex_key: str | None = None):
        raw_key = bytes.fromhex(hex_key) if hex_key else self._load_key()
        if len(raw_key) != 32:
            raise ValueError("AES key must be exactly 32 bytes (256 bits).")
        self._aesgcm = AESGCM(raw_key)

    @staticmethod
    def _load_key() -> bytes:
        """Get the key from the env variable, or fall back to the test key."""
        env_key = os.environ.get("AES_KEY")
        if env_key:
            return bytes.fromhex(env_key)
        # test key only!! a real system would keep the key in a key vault
        return hashlib.sha256(b"prototype-aes-key-do-not-use-in-production").digest()

    def _encrypt_field(self, plaintext: str) -> str:
        """Encrypt one field. Returns base64 so it can be saved as TEXT."""
        nonce = os.urandom(12)  # GCM wants a 12 byte nonce, new one every time
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode(), None)
        payload = {"n": b64encode(nonce).decode(), "c": b64encode(ciphertext).decode()}
        return b64encode(json.dumps(payload).encode()).decode()

    def _decrypt_field(self, encoded: str) -> str:
        """Opposite of _encrypt_field."""
        payload = json.loads(b64decode(encoded).decode())
        nonce = b64decode(payload["n"])
        ciphertext = b64decode(payload["c"])
        return self._aesgcm.decrypt(nonce, ciphertext, None).decode()

    def encrypt_voter(self, full_name: str, address: str, dob: str) -> dict:
        """Encrypts all 3 fields, returns a dict that matches the electors columns."""
        return {
            "full_name_enc": self._encrypt_field(full_name),
            "address_enc":   self._encrypt_field(address),
            "dob_enc":       self._encrypt_field(dob),
        }

    def decrypt_voter(self, record: dict) -> dict:
        """Takes the encrypted columns and gives back the normal values."""
        return {
            "full_name": self._decrypt_field(record["full_name_enc"]),
            "address":   self._decrypt_field(record["address_enc"]),
            "dob":       self._decrypt_field(record["dob_enc"]),
        }


def init_elector_table(conn: sqlite3.Connection) -> None:
    """electors table - the personal details are only ever stored encrypted."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS electors (
            elector_id   TEXT PRIMARY KEY,
            full_name_enc TEXT NOT NULL,
            address_enc   TEXT NOT NULL,
            dob_enc       TEXT NOT NULL,
            has_voted     INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT NOT NULL
        )
    """)
    conn.commit()


def insert_elector(conn: sqlite3.Connection, pii: PIIEncryption,
                   elector_id: str, full_name: str,
                   address: str, dob: str) -> None:
    """Add a new voter (details get encrypted first)."""
    encrypted = pii.encrypt_voter(full_name, address, dob)
    conn.execute("""
        INSERT INTO electors (elector_id, full_name_enc, address_enc,
                              dob_enc, has_voted, created_at)
        VALUES (?, ?, ?, ?, 0, ?)
    """, (
        elector_id,
        encrypted["full_name_enc"],
        encrypted["address_enc"],
        encrypted["dob_enc"],
        _now_iso(),
    ))
    conn.commit()


def fetch_elector_plaintext(conn: sqlite3.Connection, pii: PIIEncryption,
                            elector_id: str) -> dict | None:
    """Look up a voter and decrypt their details. Returns None if not found."""
    row = conn.execute(
        "SELECT full_name_enc, address_enc, dob_enc FROM electors WHERE elector_id = ?",
        (elector_id,)
    ).fetchone()
    if row is None:
        return None
    record = {"full_name_enc": row[0], "address_enc": row[1], "dob_enc": row[2]}
    return pii.decrypt_voter(record)


# ===========================================================================
# Req 9 - hash chained audit log
# ===========================================================================

def init_audit_table(conn: sqlite3.Connection) -> None:
    """
    audit_log table.

    The main idea: every row stores the hash of the row before it (prev_hash)
    and its own hash (row_hash), which is SHA-256 of all its columns + prev_hash.
    So if someone edits or deletes an old row, all the hashes after it stop
    matching and verify_audit_chain() picks it up. The first row has no
    prev_hash so we use "GENESIS" instead.

    event_type is stuff like LOGIN, VOTE_CAST, ENROL. detail is JSON.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            entry_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            actor_id   TEXT NOT NULL,
            detail     TEXT NOT NULL DEFAULT '{}',
            timestamp  TEXT NOT NULL,
            row_hash   TEXT NOT NULL,
            prev_hash  TEXT
        )
    """)
    # NOTE: SQLite can't actually block UPDATE/DELETE on a table, so "append
    # only" here just means we only ever write through append_audit_event().
    # (the postgres version in the main app uses triggers to block it properly)
    conn.commit()


def _compute_row_hash(entry_id: int | str, event_type: str, actor_id: str,
                      detail: str, timestamp: str, prev_hash: str | None) -> str:
    """SHA-256 of one row, with the fields joined by |"""
    prev = prev_hash or "GENESIS"
    raw = f"{entry_id}|{event_type}|{actor_id}|{detail}|{timestamp}|{prev}"
    return hashlib.sha256(raw.encode()).hexdigest()


def append_audit_event(conn: sqlite3.Connection, event_type: str,
                       actor_id: str, detail: dict | None = None) -> int:
    """Add an entry to the audit log and link it to the previous one. Returns the entry_id."""
    detail_str = json.dumps(detail or {})
    timestamp = _now_iso()

    # get the last row so we can link to its hash
    tip = conn.execute(
        "SELECT entry_id, row_hash FROM audit_log ORDER BY entry_id DESC LIMIT 1"
    ).fetchone()
    prev_hash = tip[1] if tip else None

    # entry_id is part of the hash but autoincrement only gives it to us after
    # the insert, so work out what the next id will be first
    next_id = (tip[0] + 1) if tip else 1
    row_hash = _compute_row_hash(next_id, event_type, actor_id,
                                 detail_str, timestamp, prev_hash)

    conn.execute("""
        INSERT INTO audit_log (event_type, actor_id, detail,
                               timestamp, row_hash, prev_hash)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (event_type, actor_id, detail_str, timestamp, row_hash, prev_hash))
    conn.commit()

    actual_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return actual_id


def verify_audit_chain(conn: sqlite3.Connection) -> tuple[bool, str]:
    """
    Goes through the whole log from the start and re-checks every hash.
    Returns (True, "OK") if nothing's wrong, otherwise (False, reason).
    """
    rows = conn.execute(
        "SELECT entry_id, event_type, actor_id, detail, "
        "timestamp, row_hash, prev_hash "
        "FROM audit_log ORDER BY entry_id ASC"
    ).fetchall()

    if not rows:
        return True, "OK – no entries yet."

    previous_hash = None
    for row in rows:
        entry_id, event_type, actor_id, detail, timestamp, stored_hash, prev_hash = row

        # does it point at the row before it? (catches deleted rows)
        if prev_hash != previous_hash:
            return False, (
                f"Chain break at entry_id={entry_id}: "
                f"stored prev_hash='{prev_hash}' does not match "
                f"expected='{previous_hash}'."
            )

        # recalculate the hash - if it's different the row was edited
        expected_hash = _compute_row_hash(
            entry_id, event_type, actor_id, detail, timestamp, prev_hash
        )
        if stored_hash != expected_hash:
            return False, (
                f"Hash mismatch at entry_id={entry_id}: "
                f"stored='{stored_hash}' expected='{expected_hash}'."
            )

        previous_hash = stored_hash

    return True, "OK"


# ===========================================================================
# Req 10 - ballots that can't be linked to the voter
# ===========================================================================

def init_ballot_table(conn: sqlite3.Connection) -> None:
    """
    Makes ballot_tokens and ballot_box.

    ballot_box deliberately has no elector_id, no IP address and no
    timestamp, so there's nothing to join it to the electors table with.
    The voter gets a one-time token (in ballot_tokens) and once they vote
    the token is deleted, so after that the link is just gone.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ballot_tokens (
            token      TEXT PRIMARY KEY,
            elector_id TEXT NOT NULL,
            issued_at  TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ballot_box (
            ballot_id    TEXT PRIMARY KEY,
            house_prefs  TEXT NOT NULL,
            senate_prefs TEXT NOT NULL
        )
    """)
    conn.commit()


def issue_ballot_token(conn: sqlite3.Connection, elector_id: str) -> str:
    """
    Gives the voter a one-time token so they can vote.

    has_voted gets set to 1 in the same transaction so they can't get a
    second token and vote twice (this kind of overlaps with Req 7).
    Raises RuntimeError if the voter doesn't exist or already voted.
    """
    with conn:
        row = conn.execute(
            "SELECT has_voted FROM electors WHERE elector_id = ?",
            (elector_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Elector '{elector_id}' not found.")
        if row[0] == 1:
            raise RuntimeError(f"Elector '{elector_id}' has already voted.")

        token = os.urandom(32).hex()
        conn.execute(
            "UPDATE electors SET has_voted = 1 WHERE elector_id = ?",
            (elector_id,)
        )
        conn.execute(
            "INSERT INTO ballot_tokens (token, elector_id, issued_at) VALUES (?, ?, ?)",
            (token, elector_id, _now_iso())
        )
    return token


def submit_ballot(conn: sqlite3.Connection, token: str,
                  house_prefs: list[int], senate_prefs: dict) -> str:
    """
    Checks the token, saves the ballot, then deletes the token.
    Returns the ballot_id. Raises RuntimeError if the token is wrong or used.
    """
    with conn:
        token_row = conn.execute(
            "SELECT elector_id FROM ballot_tokens WHERE token = ?",
            (token,)
        ).fetchone()
        if token_row is None:
            raise RuntimeError("Invalid or already-used ballot token.")

        ballot_id = os.urandom(16).hex()
        conn.execute("""
            INSERT INTO ballot_box (ballot_id, house_prefs, senate_prefs)
            VALUES (?, ?, ?)
        """, (
            ballot_id,
            json.dumps(house_prefs),
            json.dumps(senate_prefs),
        ))
        # delete the token - after this nothing links the voter to the ballot
        conn.execute("DELETE FROM ballot_tokens WHERE token = ?", (token,))

    return ballot_id


def count_ballots(conn: sqlite3.Connection) -> int:
    """How many ballots have been cast."""
    row = conn.execute("SELECT COUNT(*) FROM ballot_box").fetchone()
    return row[0]


# ===========================================================================
# Req 11 - encrypted backups + checksum
# ===========================================================================

def _snapshot_key(hex_key: str | None) -> bytes:
    """Same key as Req 8: the one passed in, else AES_KEY, else the test key."""
    return bytes.fromhex(hex_key) if hex_key else PIIEncryption._load_key()


def create_encrypted_snapshot(db_path: str, backup_dir: str,
                              hex_key: str | None = None) -> dict:
    """
    Backs up a SQLite database, encrypts it and writes a checksum file next to it.

    How it works:
      - copy the db to a temp file using sqlite's backup() (this works even
        while the db is being used, unlike just copying the file)
      - encrypt it and write the checksum (write_encrypted_snapshot below)
      - delete the temp copy so there's no unencrypted backup lying around

    Returns a dict with snapshot_file, checksum_file, sha256 and timestamp.
    """
    # copy the live db to a temp file
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    try:
        src_conn = sqlite3.connect(db_path)
        dst_conn = sqlite3.connect(tmp_path)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

        with open(tmp_path, "rb") as f:
            raw_bytes = f.read()
    finally:
        os.remove(tmp_path)  # don't leave the unencrypted copy behind

    return write_encrypted_snapshot(raw_bytes, backup_dir, hex_key)


def write_encrypted_snapshot(raw_bytes: bytes, backup_dir: str,
                             hex_key: str | None = None) -> dict:
    """
    Encrypts a database copy with AES-256-GCM and writes a checksum file next to it.
    Used for SQLite (above) and for the app's PostgreSQL dump (backup.py).

      - save it as <timestamp>.db.enc
      - save the SHA-256 of the encrypted file in <timestamp>.db.enc.sha256

    Returns a dict with snapshot_file, checksum_file, sha256 and timestamp.
    """
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    snapshot_name = f"{timestamp}.db.enc"
    checksum_name = f"{timestamp}.db.enc.sha256"
    snapshot_path = os.path.join(backup_dir, snapshot_name)
    checksum_path = os.path.join(backup_dir, checksum_name)

    aesgcm = AESGCM(_snapshot_key(hex_key))
    nonce = os.urandom(12)
    encrypted_blob = nonce + aesgcm.encrypt(nonce, raw_bytes, None)

    with open(snapshot_path, "wb") as f:
        f.write(encrypted_blob)

    # checksum is of the ENCRYPTED file, so you can check it without the key
    sha256_hex = hashlib.sha256(encrypted_blob).hexdigest()
    with open(checksum_path, "w") as f:
        f.write(f"{sha256_hex}  {snapshot_name}\n")

    return {
        "snapshot_file": snapshot_path,
        "checksum_file": checksum_path,
        "sha256":        sha256_hex,
        "timestamp":     timestamp,
    }


def verify_snapshot_checksum(snapshot_path: str, checksum_path: str) -> tuple[bool, str]:
    """Re-hash the backup and compare it to the .sha256 file. Returns (ok, message)."""
    if not os.path.exists(snapshot_path):
        return False, f"Snapshot file not found: {snapshot_path}"
    if not os.path.exists(checksum_path):
        return False, f"Checksum file not found: {checksum_path}"

    with open(snapshot_path, "rb") as f:
        actual_sha256 = hashlib.sha256(f.read()).hexdigest()

    with open(checksum_path, "r") as f:
        stored_sha256 = f.read().strip().split()[0]

    if actual_sha256 == stored_sha256:
        return True, "OK"
    return False, (
        f"Checksum mismatch: "
        f"stored={stored_sha256} actual={actual_sha256}"
    )


def restore_snapshot(snapshot_path: str, restore_path: str,
                     hex_key: str | None = None) -> None:
    """
    Decrypts a backup back into the original file (SQLite db or SQL dump).
    If the file was changed at all, GCM's tag check fails and it raises an
    error instead of writing out a broken db.
    """
    aesgcm = AESGCM(_snapshot_key(hex_key))

    with open(snapshot_path, "rb") as f:
        encrypted_blob = f.read()

    nonce = encrypted_blob[:12]
    ciphertext = encrypted_blob[12:]
    raw_bytes = aesgcm.decrypt(nonce, ciphertext, None)  # errors if tampered with

    with open(restore_path, "wb") as f:
        f.write(raw_bytes)

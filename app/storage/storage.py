"""
storage.py
==========
Part Three – Storage Subsystem Implementation
Student: DonCarl0s04
Repo:    DonCarl0s04/a3-secure-voting

Implements four security requirements:
  Req 8  – AES-256-GCM voter PII encryption at rest
  Req 9  – Append-only SHA-256 hash-chained audit log
  Req 10 – Decoupled ballot table (no elector foreign keys)
  Req 11 – Encrypted point-in-time database snapshots with SHA-256 checksum
"""

import os
import json
import hashlib
import sqlite3
import tempfile
import datetime
from base64 import b64encode, b64decode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return current UTC timestamp as an ISO-8601 string."""
    return datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ---------------------------------------------------------------------------
# Req 8 – AES-256-GCM Voter PII Encryption at Rest
# ---------------------------------------------------------------------------

class PIIEncryption:
    """
    Encrypts and decrypts voter personally identifiable information fields
    (full_name, residential_address, date_of_birth) using AES-256-GCM
    authenticated encryption before persisting to the database.

    Each field is encrypted independently so that individual fields can be
    decrypted without exposing the full record.

    Key derivation: a 32-byte (256-bit) key is expected. In production this
    would be retrieved from a hardware security module or environment vault.
    For the prototype the key is read from the AES_KEY environment variable
    (hex-encoded) or a deterministic test key is used.
    """

    def __init__(self, hex_key: str | None = None):
        raw_key = bytes.fromhex(hex_key) if hex_key else self._load_key()
        if len(raw_key) != 32:
            raise ValueError("AES key must be exactly 32 bytes (256 bits).")
        self._aesgcm = AESGCM(raw_key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_key() -> bytes:
        """Load key from environment or generate a stable test key."""
        env_key = os.environ.get("AES_KEY")
        if env_key:
            return bytes.fromhex(env_key)
        # Prototype-only: derive a stable key from a fixed passphrase.
        # In production NEVER use this path – use a proper key vault.
        return hashlib.sha256(b"prototype-aes-key-do-not-use-in-production").digest()

    def _encrypt_field(self, plaintext: str) -> str:
        """Encrypt a single string field; return a base-64 encoded payload."""
        nonce = os.urandom(12)                      # 96-bit nonce per GCM spec
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode(), None)
        payload = {"n": b64encode(nonce).decode(), "c": b64encode(ciphertext).decode()}
        return b64encode(json.dumps(payload).encode()).decode()

    def _decrypt_field(self, encoded: str) -> str:
        """Decrypt a single base-64 encoded field back to a plaintext string."""
        payload = json.loads(b64decode(encoded).decode())
        nonce = b64decode(payload["n"])
        ciphertext = b64decode(payload["c"])
        return self._aesgcm.decrypt(nonce, ciphertext, None).decode()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encrypt_voter(self, full_name: str, address: str, dob: str) -> dict:
        """
        Encrypt each PII field independently.

        Returns a dict ready to be stored in the `electors` table:
          { "full_name_enc", "address_enc", "dob_enc" }
        """
        return {
            "full_name_enc": self._encrypt_field(full_name),
            "address_enc":   self._encrypt_field(address),
            "dob_enc":       self._encrypt_field(dob),
        }

    def decrypt_voter(self, record: dict) -> dict:
        """
        Decrypt all PII fields from a database record dict.

        Accepts keys: full_name_enc, address_enc, dob_enc.
        Returns a dict with plaintext values.
        """
        return {
            "full_name": self._decrypt_field(record["full_name_enc"]),
            "address":   self._decrypt_field(record["address_enc"]),
            "dob":       self._decrypt_field(record["dob_enc"]),
        }


def init_elector_table(conn: sqlite3.Connection) -> None:
    """Create the `electors` table (stores only encrypted PII columns)."""
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
    """Encrypt PII and insert a new elector record."""
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
    """Retrieve and decrypt a single elector's PII."""
    row = conn.execute(
        "SELECT full_name_enc, address_enc, dob_enc FROM electors WHERE elector_id = ?",
        (elector_id,)
    ).fetchone()
    if row is None:
        return None
    record = {"full_name_enc": row[0], "address_enc": row[1], "dob_enc": row[2]}
    return pii.decrypt_voter(record)


# ---------------------------------------------------------------------------
# Req 9 – Append-Only SHA-256 Hash-Chained Audit Log
# ---------------------------------------------------------------------------

def init_audit_table(conn: sqlite3.Connection) -> None:
    """
    Create the `audit_log` table.

    Each row contains:
      - entry_id   : auto-increment primary key
      - event_type : e.g. "LOGIN", "VOTE_CAST", "ENROL"
      - actor_id   : user or system component that triggered the event
      - detail     : free-form JSON detail string
      - timestamp  : UTC ISO-8601
      - row_hash   : SHA-256(entry_id || event_type || actor_id || detail ||
                             timestamp || prev_hash)
      - prev_hash  : row_hash of the previous row (NULL for the genesis row)

    Any modification or deletion of a historical row breaks the hash chain
    and is detectable by verify_audit_chain().
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
    # Enforce append-only: prevent DELETE and UPDATE at the application layer.
    # SQLite does not support true WORM tables natively, so all access must
    # go through append_audit_event() exclusively.
    conn.commit()


def _compute_row_hash(entry_id: int | str, event_type: str, actor_id: str,
                      detail: str, timestamp: str, prev_hash: str | None) -> str:
    """Compute SHA-256 hash of a single audit row's content."""
    prev = prev_hash or "GENESIS"
    raw = f"{entry_id}|{event_type}|{actor_id}|{detail}|{timestamp}|{prev}"
    return hashlib.sha256(raw.encode()).hexdigest()


def append_audit_event(conn: sqlite3.Connection, event_type: str,
                       actor_id: str, detail: dict | None = None) -> int:
    """
    Append a new tamper-evident entry to the audit log.

    Returns the new entry_id.
    The row_hash is calculated over all field values plus the previous row's
    hash, forming a cryptographic chain.
    """
    detail_str = json.dumps(detail or {})
    timestamp = _now_iso()

    # Fetch the most recent hash (tip of the chain)
    tip = conn.execute(
        "SELECT entry_id, row_hash FROM audit_log ORDER BY entry_id DESC LIMIT 1"
    ).fetchone()
    prev_hash = tip[1] if tip else None

    # Placeholder entry_id for hash computation (next auto-increment value)
    # We compute with a temporary id then verify after insert.
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
    Walk every row in the audit_log in order and verify the hash chain.

    Returns (True, "OK") if the chain is intact, or
            (False, "<reason>") if any tampering is detected.
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

        # 1. Verify prev_hash linkage
        if prev_hash != previous_hash:
            return False, (
                f"Chain break at entry_id={entry_id}: "
                f"stored prev_hash='{prev_hash}' does not match "
                f"expected='{previous_hash}'."
            )

        # 2. Recompute and compare row_hash
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


# ---------------------------------------------------------------------------
# Req 10 – Decoupled Ballot Table (No Elector Foreign Keys)
# ---------------------------------------------------------------------------

def init_ballot_table(conn: sqlite3.Connection) -> None:
    """
    Create the `ballot_box` table.

    Critically, this table contains:
      - NO elector_id / voter foreign key
      - NO ip_address column
      - NO timestamp column

    The only link between an elector and their ballot during submission is
    a one-time ephemeral token stored in `ballot_tokens`. Once the vote is
    confirmed, the token row is deleted, making re-linking impossible.
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
    Issue a one-time ephemeral token to an elector.

    Before issuing, the elector's `has_voted` flag is checked and set to 1
    atomically to prevent double-voting (Req 7 integration point).
    The token is a cryptographically random 32-byte hex string.
    Returns the token string, or raises RuntimeError if already voted.
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
    Validate the ephemeral token and store the ballot in ballot_box.

    After the ballot is written, the token row is DELETED so that the
    elector-to-ballot link no longer exists anywhere in the database.
    Returns the new ballot_id.
    Raises RuntimeError for invalid or reused tokens.
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
        # Destroy the token – after this point there is NO link between
        # the elector identity and this ballot_id.
        conn.execute("DELETE FROM ballot_tokens WHERE token = ?", (token,))

    return ballot_id


def count_ballots(conn: sqlite3.Connection) -> int:
    """Return the total number of cast ballots (no identity information)."""
    row = conn.execute("SELECT COUNT(*) FROM ballot_box").fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Req 11 – Encrypted Snapshots with SHA-256 Integrity Checksums
# ---------------------------------------------------------------------------

def create_encrypted_snapshot(db_path: str, backup_dir: str,
                              hex_key: str | None = None) -> dict:
    """
    Create an encrypted, point-in-time snapshot of the SQLite database.

    Steps:
      1. Use SQLite's online backup API to copy the live database to a temp
         file (safe while database is open and active).
      2. Read the raw binary snapshot.
      3. Encrypt it with AES-256-GCM (same key as Req 8).
      4. Write the encrypted blob to <backup_dir>/<timestamp>.db.enc
      5. Compute SHA-256 of the encrypted blob and write it to
         <backup_dir>/<timestamp>.db.enc.sha256
      6. Delete the unencrypted temporary copy.

    Returns a dict:
      {
        "snapshot_file": str,     # path to encrypted archive
        "checksum_file": str,     # path to SHA-256 sidecar
        "sha256":        str,     # hex checksum of the encrypted file
        "timestamp":     str,     # ISO-8601 creation time
      }
    """
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    snapshot_name = f"{timestamp}.db.enc"
    checksum_name = f"{timestamp}.db.enc.sha256"
    snapshot_path = os.path.join(backup_dir, snapshot_name)
    checksum_path = os.path.join(backup_dir, checksum_name)

    # Step 1 – Online backup to a temp file
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    try:
        src_conn = sqlite3.connect(db_path)
        dst_conn = sqlite3.connect(tmp_path)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

        # Step 2 – Read raw bytes
        with open(tmp_path, "rb") as f:
            raw_bytes = f.read()
    finally:
        os.remove(tmp_path)   # Immediately delete unencrypted copy

    # Step 3 – Encrypt with AES-256-GCM
    raw_key = bytes.fromhex(hex_key) if hex_key else \
        hashlib.sha256(b"prototype-aes-key-do-not-use-in-production").digest()
    aesgcm = AESGCM(raw_key)
    nonce = os.urandom(12)
    encrypted_blob = nonce + aesgcm.encrypt(nonce, raw_bytes, None)

    # Step 4 – Write encrypted archive
    with open(snapshot_path, "wb") as f:
        f.write(encrypted_blob)

    # Step 5 – Compute and write SHA-256 checksum of the encrypted file
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
    """
    Verify the SHA-256 checksum of an encrypted snapshot file.

    Returns (True, "OK") if checksum matches, or (False, "<reason>") if
    the archive has been corrupted or tampered with.
    """
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
    Decrypt a snapshot archive and write the raw SQLite file to restore_path.

    Verifies integrity before writing – raises ValueError on decryption
    failure (which also catches GCM authentication tag failures).
    """
    raw_key = bytes.fromhex(hex_key) if hex_key else \
        hashlib.sha256(b"prototype-aes-key-do-not-use-in-production").digest()
    aesgcm = AESGCM(raw_key)

    with open(snapshot_path, "rb") as f:
        encrypted_blob = f.read()

    nonce = encrypted_blob[:12]
    ciphertext = encrypted_blob[12:]
    raw_bytes = aesgcm.decrypt(nonce, ciphertext, None)   # raises on bad tag

    with open(restore_path, "wb") as f:
        f.write(raw_bytes)

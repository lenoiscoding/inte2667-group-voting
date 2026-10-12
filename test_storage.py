"""
test_storage.py - tests for storage.py
DonCarl0s04

5 tests for each of my requirements (8, 9, 10, 11) so 20 altogether.
Run with:  pytest test_storage.py -v
"""

import os
import sqlite3
import tempfile
import unittest

from storage import (
    # Req 8
    PIIEncryption,
    init_elector_table,
    insert_elector,
    fetch_elector_plaintext,
    # Req 9
    init_audit_table,
    append_audit_event,
    verify_audit_chain,
    # Req 10
    init_ballot_table,
    issue_ballot_token,
    submit_ballot,
    # Req 11
    create_encrypted_snapshot,
    verify_snapshot_checksum,
    restore_snapshot,
)


# ---- helpers ----

def _make_db() -> sqlite3.Connection:
    """Fresh in-memory db with all the tables, so each test starts clean."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    init_elector_table(conn)
    init_audit_table(conn)
    init_ballot_table(conn)
    return conn


def _seed_elector(conn, pii, elector_id="E001",
                  name="Jane Doe", address="10 Smith St, Sydney NSW 2000",
                  dob="1990-05-14"):
    insert_elector(conn, pii, elector_id, name, address, dob)


# ===========================================================================
# Req 8 - voter details encryption
# ===========================================================================

class TestReq8PIIEncryption(unittest.TestCase):
    """Req 8 tests."""

    def setUp(self):
        self.pii = PIIEncryption()
        self.conn = _make_db()

    def tearDown(self):
        self.conn.close()

    # T8-01
    def test_encrypted_fields_are_not_plaintext(self):
        """Whats actually saved in the db shouldn't have the real name/address in it."""
        _seed_elector(self.conn, self.pii)
        row = self.conn.execute(
            "SELECT full_name_enc, address_enc, dob_enc FROM electors WHERE elector_id='E001'"
        ).fetchone()
        self.assertIsNotNone(row, "Elector record should exist in database.")
        self.assertNotIn("Jane",    row[0], "Plaintext name must not appear in DB.")
        self.assertNotIn("Smith St", row[1], "Plaintext address must not appear in DB.")
        self.assertNotIn("1990",    row[2], "Plaintext DOB must not appear in DB.")

    # T8-02
    def test_decrypt_returns_correct_plaintext(self):
        """Decrypting should give back exactly what we put in."""
        _seed_elector(self.conn, self.pii)
        result = fetch_elector_plaintext(self.conn, self.pii, "E001")
        self.assertIsNotNone(result)
        self.assertEqual(result["full_name"], "Jane Doe")
        self.assertEqual(result["address"],   "10 Smith St, Sydney NSW 2000")
        self.assertEqual(result["dob"],       "1990-05-14")

    # T8-03
    def test_different_nonces_produce_different_ciphertexts(self):
        """
        Encrypting the same name twice should give different results because
        of the random nonce (otherwise you could spot people with the same name).
        """
        enc1 = self.pii.encrypt_voter("Jane Doe", "10 Smith St", "1990-05-14")
        enc2 = self.pii.encrypt_voter("Jane Doe", "10 Smith St", "1990-05-14")
        self.assertNotEqual(
            enc1["full_name_enc"], enc2["full_name_enc"],
            "Ciphertext must differ across calls due to random nonces."
        )

    # T8-04
    def test_wrong_key_cannot_decrypt(self):
        """Using the wrong key should fail, not give back garbage."""
        alt_pii = PIIEncryption(hex_key=os.urandom(32).hex())
        _seed_elector(self.conn, self.pii)
        row = self.conn.execute(
            "SELECT full_name_enc, address_enc, dob_enc FROM electors WHERE elector_id='E001'"
        ).fetchone()
        record = {"full_name_enc": row[0], "address_enc": row[1], "dob_enc": row[2]}
        with self.assertRaises(Exception):
            alt_pii.decrypt_voter(record)

    # T8-05
    def test_nonexistent_elector_returns_none(self):
        """Looking up a voter that doesn't exist just gives None."""
        result = fetch_elector_plaintext(self.conn, self.pii, "DOES_NOT_EXIST")
        self.assertIsNone(result)


# ===========================================================================
# Req 9 - hash chained audit log
# ===========================================================================

class TestReq9AuditLog(unittest.TestCase):
    """Req 9 tests."""

    def setUp(self):
        self.conn = _make_db()

    def tearDown(self):
        self.conn.close()

    # T9-01
    def test_single_event_chain_is_valid(self):
        """One entry on its own should pass."""
        append_audit_event(self.conn, "LOGIN", "admin_01", {"ip": "10.0.0.1"})
        ok, msg = verify_audit_chain(self.conn)
        self.assertTrue(ok, f"Chain should be valid after single entry: {msg}")

    # T9-02
    def test_multiple_events_chain_is_valid(self):
        """A few entries in a row should all link up properly."""
        for i in range(5):
            append_audit_event(self.conn, "VOTE_CAST", f"elector_{i}")
        ok, msg = verify_audit_chain(self.conn)
        self.assertTrue(ok, f"Chain should be valid after 5 entries: {msg}")

    # T9-03
    def test_modified_row_breaks_chain(self):
        """If someone edits a row straight in the db, the check should catch it."""
        append_audit_event(self.conn, "ENROL",    "elector_A")
        append_audit_event(self.conn, "VOTE_CAST", "elector_A")
        # pretend to be an attacker and change the first row
        self.conn.execute(
            "UPDATE audit_log SET detail = '{\"tampered\": true}' WHERE entry_id = 1"
        )
        self.conn.commit()
        ok, msg = verify_audit_chain(self.conn)
        self.assertFalse(ok, "Chain verification must fail after row tampering.")
        self.assertIn("entry_id=1", msg)

    # T9-04
    def test_empty_log_passes_verification(self):
        """No entries yet = nothing to break, so it should pass."""
        ok, msg = verify_audit_chain(self.conn)
        self.assertTrue(ok, f"Empty log should pass: {msg}")

    # T9-05
    def test_audit_entries_are_never_deleted(self):
        """
        Deleting an old entry should break the chain (like someone trying
        to cover their tracks).
        """
        append_audit_event(self.conn, "LOGIN", "admin_01")
        append_audit_event(self.conn, "LOGOUT", "admin_01")
        # delete the first entry
        self.conn.execute("DELETE FROM audit_log WHERE entry_id = 1")
        self.conn.commit()
        ok, _ = verify_audit_chain(self.conn)
        self.assertFalse(ok, "Chain must be broken after deleting a historical entry.")


# ===========================================================================
# Req 10 - ballots not linked to voters
# ===========================================================================

class TestReq10BallotDecoupling(unittest.TestCase):
    """Req 10 tests."""

    def setUp(self):
        self.pii = PIIEncryption()
        self.conn = _make_db()
        _seed_elector(self.conn, self.pii, elector_id="E100")

    def tearDown(self):
        self.conn.close()

    # T10-01
    def test_ballot_box_has_no_elector_id_column(self):
        """ballot_box shouldn't have any column that could identify the voter."""
        cursor = self.conn.execute("PRAGMA table_info(ballot_box)")
        columns = [row[1] for row in cursor.fetchall()]
        forbidden = {"elector_id", "voter_id", "user_id", "ip_address", "timestamp"}
        overlap = forbidden & set(columns)
        self.assertEqual(
            overlap, set(),
            f"ballot_box must not contain identity columns: {overlap}"
        )

    # T10-02
    def test_token_deleted_after_vote_submission(self):
        """After voting the token should be gone from ballot_tokens."""
        token = issue_ballot_token(self.conn, "E100")
        submit_ballot(self.conn, token, [1, 2, 3], {"atl": [1, 2, 3, 4, 5, 6]})
        row = self.conn.execute(
            "SELECT * FROM ballot_tokens WHERE token = ?", (token,)
        ).fetchone()
        self.assertIsNone(row, "Token must be deleted after ballot submission.")

    # T10-03
    def test_ballot_stored_without_voter_link(self):
        """The saved ballot row shouldn't contain the voter's ID anywhere."""
        token = issue_ballot_token(self.conn, "E100")
        ballot_id = submit_ballot(
            self.conn, token, [1, 2, 3], {"atl": [1, 2, 3, 4, 5, 6]}
        )
        row = self.conn.execute(
            "SELECT * FROM ballot_box WHERE ballot_id = ?", (ballot_id,)
        ).fetchone()
        self.assertIsNotNone(row, "Ballot should be stored in ballot_box.")
        # just check the whole row as a string
        row_str = str(row)
        self.assertNotIn("E100", row_str, "Elector ID must not appear in ballot_box row.")

    # T10-04
    def test_cannot_vote_twice(self):
        """Using the same token again should be rejected."""
        token = issue_ballot_token(self.conn, "E100")
        submit_ballot(self.conn, token, [1, 2], {"atl": [1, 2, 3, 4, 5, 6]})
        # try to vote again
        with self.assertRaises(RuntimeError):
            submit_ballot(self.conn, token, [2, 1], {"atl": [6, 5, 4, 3, 2, 1]})

    # T10-05
    def test_cannot_issue_second_token_after_voting(self):
        """Someone who already voted shouldn't be able to get another token."""
        token = issue_ballot_token(self.conn, "E100")
        submit_ballot(self.conn, token, [1, 2, 3], {"atl": [1, 2, 3, 4, 5, 6]})
        with self.assertRaises(RuntimeError):
            issue_ballot_token(self.conn, "E100")


# ===========================================================================
# Req 11 - encrypted backups
# ===========================================================================

class TestReq11EncryptedSnapshots(unittest.TestCase):
    """Req 11 tests."""

    def setUp(self):
        # backup needs an actual file, not :memory:, so make a temp db
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        conn = sqlite3.connect(self.db_path)
        init_elector_table(conn)
        pii = PIIEncryption()
        _seed_elector(conn, pii, elector_id="SNAP_E001")
        conn.commit()
        conn.close()

        self.backup_dir = tempfile.mkdtemp()
        self.restore_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        os.remove(self.db_path)
        shutil.rmtree(self.backup_dir)
        shutil.rmtree(self.restore_dir)

    # T11-01
    def test_snapshot_files_are_created(self):
        """Should make both the .enc file and the .sha256 file."""
        result = create_encrypted_snapshot(self.db_path, self.backup_dir)
        self.assertTrue(
            os.path.exists(result["snapshot_file"]),
            "Encrypted snapshot file must exist."
        )
        self.assertTrue(
            os.path.exists(result["checksum_file"]),
            "SHA-256 checksum sidecar file must exist."
        )

    # T11-02
    def test_snapshot_is_not_plaintext_sqlite(self):
        """A normal SQLite file starts with "SQLite format 3", the backup shouldn't."""
        result = create_encrypted_snapshot(self.db_path, self.backup_dir)
        with open(result["snapshot_file"], "rb") as f:
            header = f.read(16)
        sqlite_magic = b"SQLite format 3\x00"
        self.assertNotEqual(
            header, sqlite_magic,
            "Snapshot must be encrypted – must not start with SQLite magic bytes."
        )

    # T11-03
    def test_checksum_verification_passes(self):
        """Checksum should match if nobody touched the file."""
        result = create_encrypted_snapshot(self.db_path, self.backup_dir)
        ok, msg = verify_snapshot_checksum(
            result["snapshot_file"], result["checksum_file"]
        )
        self.assertTrue(ok, f"Checksum should match for fresh snapshot: {msg}")

    # T11-04
    def test_tampered_snapshot_fails_checksum(self):
        """Changing even one byte should make the checksum fail."""
        result = create_encrypted_snapshot(self.db_path, self.backup_dir)
        # change a byte in the middle of the file
        with open(result["snapshot_file"], "r+b") as f:
            f.seek(100)
            byte = f.read(1)
            f.seek(100)
            f.write(bytes([byte[0] ^ 0xFF]))   # bit-flip
        ok, msg = verify_snapshot_checksum(
            result["snapshot_file"], result["checksum_file"]
        )
        self.assertFalse(ok, "Tampered snapshot must fail checksum verification.")
        self.assertIn("mismatch", msg)

    # T11-05
    def test_restore_produces_valid_sqlite_database(self):
        """Restoring should give a working db with the voter still in it."""
        result = create_encrypted_snapshot(self.db_path, self.backup_dir)
        restored = os.path.join(self.restore_dir, "restored.db")
        restore_snapshot(result["snapshot_file"], restored)

        # open it and check the data is there
        conn = sqlite3.connect(restored)
        row = conn.execute(
            "SELECT elector_id FROM electors WHERE elector_id='SNAP_E001'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row, "Restored database must contain original data.")


if __name__ == "__main__":
    unittest.main(verbosity=2)

# Storage Subsystem – Part Three Implementation Guide

**Student:** s4129654_Don_Carlos_Porte\
**Repo:** inte2667-group-voting\
**Subsystem:** Data Storage & Audit

---

## Overview

This subsystem implements 4 security requirements from Part One of the assignment, covering all database-level and backup-level security controls for the Electronic Voting Platform.

---

## Requirements Implemented

| Req ID | Description | Complexity | File |
| --- | --- | --- | --- |
| **8** | AES-256-GCM encryption of voter PII at rest | High | `storage.py` |
| **9** | Append-only SHA-256 hash-chained audit log | Medium | `storage.py` |
| **10** | Decoupled ballot table (no elector foreign keys) | High | `storage.py` |
| **11** | Encrypted DB snapshots with SHA-256 checksums | High | `storage.py` |

---

## File Structure

```
a3-secure-voting/
├── storage/
│   ├── storage.py          ← Core implementation (all 4 requirements)
│   ├── test_storage.py     ← Unit tests (5 tests per requirement = 20 total)
│   └── README.md           ← This file
└── .github/
    └── workflows/
        └── storage-ci.yml  ← GitHub Actions CI pipeline
```

---

## How to Run Locally

### 1\. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2\. Run Unit Tests

```bash
cd storage
pytest test_storage.py -v
```

### 3\. Run Tests with Coverage Report

```bash
cd storage
pytest test_storage.py --cov=storage --cov-report=term-missing -v
```

---

## Unit Test Summary

### Req 8 – AES-256-GCM PII Encryption (5 tests)

| Test ID | Test Name | What It Proves |
| --- | --- | --- |
| T8-01 | `test_encrypted_fields_are_not_plaintext` | Raw DB values contain no readable PII |
| T8-02 | `test_decrypt_returns_correct_plaintext` | Decryption recovers exact original values |
| T8-03 | `test_different_nonces_produce_different_ciphertexts` | Each encryption uses a unique nonce |
| T8-04 | `test_wrong_key_cannot_decrypt` | Wrong key raises exception (GCM auth tag fails) |
| T8-05 | `test_nonexistent_elector_returns_none` | Safe handling of missing elector ID |

### Req 9 – Hash-Chained Audit Log (5 tests)

| Test ID | Test Name | What It Proves |
| --- | --- | --- |
| T9-01 | `test_single_event_chain_is_valid` | Single entry chain passes verification |
| T9-02 | `test_multiple_events_chain_is_valid` | Multiple entries chain correctly |
| T9-03 | `test_modified_row_breaks_chain` | Row tampering is detected |
| T9-04 | `test_empty_log_passes_verification` | Empty log is a valid chain |
| T9-05 | `test_audit_entries_are_never_deleted` | Deletion of a row breaks the chain |

### Req 10 – Decoupled Ballot Table (5 tests)

| Test ID | Test Name | What It Proves |
| --- | --- | --- |
| T10-01 | `test_ballot_box_has_no_elector_id_column` | ballot_box has no identity columns |
| T10-02 | `test_token_deleted_after_vote_submission` | Ephemeral token destroyed after use |
| T10-03 | `test_ballot_stored_without_voter_link` | No elector ID in stored ballot row |
| T10-04 | `test_cannot_vote_twice` | Reused token raises RuntimeError |
| T10-05 | `test_cannot_issue_second_token_after_voting` | Double-token issuance is blocked |

### Req 11 – Encrypted Snapshots (5 tests)

| Test ID | Test Name | What It Proves |
| --- | --- | --- |
| T11-01 | `test_snapshot_files_are_created` | Both snapshot and checksum files exist |
| T11-02 | `test_snapshot_is_not_plaintext_sqlite` | Encrypted file has no SQLite magic header |
| T11-03 | `test_checksum_verification_passes` | SHA-256 matches for untampered snapshot |
| T11-04 | `test_tampered_snapshot_fails_checksum` | Single byte flip is detected |
| T11-05 | `test_restore_produces_valid_sqlite_database` | Decrypted restore is a valid SQLite DB |

---

## Suggested Commit History

Follow this commit order so your contribution history is clean and traceable:

```
Commit 1:  "req8: init elector table schema with encrypted PII columns"
Commit 2:  "req8: implement PIIEncryption class with AES-256-GCM encrypt/decrypt"
Commit 3:  "req8: add insert_elector and fetch_elector_plaintext functions"
Commit 4:  "test-req8: add 5 unit tests for PII encryption (T8-01 to T8-05)"
Commit 5:  "req9: implement append-only audit_log table with SHA-256 hash chaining"
Commit 6:  "req9: implement verify_audit_chain integrity verifier"
Commit 7:  "test-req9: add 5 unit tests for hash-chained audit log (T9-01 to T9-05)"
Commit 8:  "req10: implement decoupled ballot_box and ballot_tokens tables"
Commit 9:  "req10: implement issue_ballot_token and submit_ballot with ephemeral token deletion"
Commit 10: "test-req10: add 5 unit tests for decoupled ballot submission (T10-01 to T10-05)"
Commit 11: "req11: implement create_encrypted_snapshot with AES-256-GCM and SHA-256 checksum"
Commit 12: "req11: implement verify_snapshot_checksum and restore_snapshot"
Commit 13: "test-req11: add 5 unit tests for encrypted snapshot integrity (T11-01 to T11-05)"
Commit 14: "ci: add GitHub Actions storage-ci.yml pipeline with lint, test, and pip-audit stages"
Commit 15: "docs: add README_storage.md with implementation guide and commit history"
```

---

## CI/CD Pipeline

The `.github/workflows/storage-ci.yml` file runs automatically on every push to any file inside `storage/`. It contains three stages:

1. **Lint** – `flake8` static analysis (max line length 100).

2. **Test** – `pytest` with coverage, fails if coverage drops below 80%.

3. **Security** – `pip-audit` scans all installed dependencies for known CVEs.

The pipeline ensures that every commit to the storage subsystem passes all unit tests before it can be merged into the main branch.

---

## Key Security Design Decisions

### Req 8 – Why AES-256-GCM?

AES-GCM is an authenticated encryption scheme. The GCM authentication tag ensures that if any byte of the ciphertext is modified, decryption raises an exception automatically. This protects against ciphertext tampering without requiring a separate HMAC calculation.

### Req 9 – Why Hash Chaining?

Each audit row's `row_hash` is computed over its own content PLUS the previous row's hash. This means that modifying, inserting, or deleting any historical row immediately invalidates all subsequent hashes. An attacker cannot rewrite history without recalculating the entire chain.

### Req 10 – Why Two Tables?

Keeping `electors` (identity) and `ballot_box` (votes) in completely separate tables with no foreign key or shared timestamp means there is no database join that can link a voter to their ballot. The ephemeral token that temporarily authorizes submission is deleted the moment the vote is recorded.

### Req 11 – Why Encrypt the Backup?

A database backup stored in plaintext is just as dangerous as the live database. Encrypting the snapshot with the same AES-256-GCM key ensures that even a stolen backup file cannot be read. The SHA-256 checksum companion file ensures the backup has not been silently corrupted or tampered with before restoration.

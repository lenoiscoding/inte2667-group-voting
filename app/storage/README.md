# Storage (Req 8–11)

This is my part of our A3 voting system. I did the **storage** side, which covers 4 of our requirements from Part 1. Everything is in `storage.py` and the tests are in `test_storage.py`.

I used SQLite for this so it runs straight away without needing a database server. The main app uses PostgreSQL, but the ideas are the same.

## What's covered

| Req | What it does | Priority / Complexity |
| --- | --- | --- |
| 8 | Encrypts voter details (name, address, DOB) with AES-256-GCM before saving them | High / High |
| 9 | Audit log where each entry is linked to the one before it with a SHA-256 hash, so edits or deletes can be detected | High / High |
| 10 | Ballots are saved in their own table with no voter ID, IP or time, so you can't tell who voted for what | High / High |
| 11 | Encrypted backups of the database, each with a `.sha256` checksum file | High / High |

## Files

```
storage/
├── storage.py          - the code for Req 8, 9, 10 and 11
├── test_storage.py     - 20 tests (5 per requirement)
├── requirements.txt    - cryptography + pytest
├── ERD_with_Storage.png / .drawio  - our ERD with the storage tables
└── README.md
```

There's also `.github/workflows/storage-ci.yml` in the root of the repo, which runs the tests on GitHub (see below).

## How to run it

```bash
cd storage
pip install -r requirements.txt
pytest test_storage.py -v
```

You should get `20 passed`. To see the coverage as well:

```bash
pytest test_storage.py --cov=storage --cov-report=term-missing
```

(you need `pip install pytest-cov` for that one)

## How each one works

**Req 8 – encryption.** Each field is encrypted on its own with AES-256-GCM using a new random 12-byte nonce, so the same name encrypted twice looks different in the database. I picked GCM over CBC + HMAC (the other option in our Part 2) because it also checks for tampering: if someone changes the stored value even slightly, decryption just fails. The key comes from the `AES_KEY` environment variable. If it isn't set, a fixed test key is used, which is only OK because this is a prototype.

**Req 9 – audit log.** Every row stores its own hash and the hash of the row before it. The hash covers all the columns plus the previous hash, so changing or deleting an old row breaks every hash after it. `verify_audit_chain()` goes through the whole log and tells you where it broke. One limitation: SQLite can't stop someone running UPDATE or DELETE directly, so this *detects* tampering rather than preventing it. (The Postgres version in the main app also has triggers that block it.)

**Req 10 – anonymous ballots.** The voter gets a one-time token, votes with it, and the token is deleted in the same transaction that saves the ballot. The `ballot_box` table has no voter ID, IP address or timestamp, so after that there's nothing left to connect a ballot to a person. `has_voted` is set when the token is given out, so nobody can get a second one.

**Req 11 – backups.** `create_encrypted_snapshot()` uses SQLite's `backup()` to take a copy while the db is still in use (just copying the file can give you a corrupted copy), encrypts it with AES-256-GCM and writes a SHA-256 checksum next to it. The temp copy is deleted straight away so there's never an unencrypted backup on disk. When restoring, you can check the checksum first, and GCM checks the file again when it decrypts.

## Tests

| Req | Tests |
| --- | --- |
| 8 | data in the db isn't readable · decrypt gives back the original · same input encrypts differently each time · wrong key fails · missing voter returns None |
| 9 | one entry passes · several entries pass · editing a row is caught · empty log passes · deleting a row is caught |
| 10 | ballot table has no voter columns · token deleted after voting · ballot row has no voter ID · can't reuse a token · can't get a second token |
| 11 | both files get created · backup isn't a readable SQLite file · checksum passes · changing one byte fails the checksum · restore gives a working db |

## CI

`storage-ci.yml` runs on GitHub whenever something in `storage/` changes. It does three things:

1. **flake8**, to check code style
2. **pytest**, which needs at least 80% coverage to pass
3. **pip-audit**, which checks `requirements.txt` for packages with known vulnerabilities

## Things I'd do differently in a real system

- keep the key in a proper key vault instead of an environment variable
- block UPDATE/DELETE on the audit log at the database level (the main app does this with Postgres triggers)
- run the backups on a schedule and store them somewhere separate from the database

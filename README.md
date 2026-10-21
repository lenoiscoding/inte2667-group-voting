# Electronic Voting Platform — Security Prototype

INTE2667 Assignment 3. A Flask web app covering the **Authentication, Registration, Voting and Storage** subsystems of the Electronic Voting Platform, built around the 22 security requirements below.

**Stack:** Python 3.11 / Flask · PostgreSQL 16 · nginx (TLS) · Docker Compose

## Run it with Docker (the real setup)

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/).

1. Create your `.env` from the template:
   ```bash
   cp .env.example .env
   ```
   Fill in `SECRET_KEY`, `JWT_SECRET_KEY`, `POSTGRES_PASSWORD` and `AES_KEY`. Generate each value with:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   The `MAIL_*` settings are optional (Req 13 email).
2. Build and start everything:
   ```bash
   docker compose up --build
   ```
3. Open **https://localhost/auth/login**. The first start creates a self-signed certificate, so the browser warns once; accept it for the demo. Plain `http://` is redirected to HTTPS.

Stop with `Ctrl+C` (or `docker compose down`). To wipe the database and start clean, run `docker compose down -v`. You need to do this once after pulling the storage changes, because the voter columns changed type.

### Try it
1. **Load the electoral roll** (Req 20). Only people on the roll can register:
   ```bash
   docker compose exec web flask --app run import-roll data/sample_electoral_roll.csv
   ```
   The people in `data/sample_electoral_roll.csv` are made up. Register as one of them, using the same name, date of birth and ID number. Morgan Lee is marked not eligible, to show a refusal.
2. **Register** (link on the login page) and scan the QR code with Google or Microsoft Authenticator. The QR code is only shown once.
3. **Log in** with your username and password, then the 6-digit code.
4. From the home page, **cast a vote** (a second vote is refused) or **view your registration history**. To change your name or address, go to `/registration/update-details`. The ballot has a House paper (number every box, Req 17) and a Senate paper (at least 6 boxes above the line or 12 below, Req 18). The server refuses an informal ballot without using it up, so the voter can fix it and resubmit.
5. **Close the polls and count the votes** (Req 19), then open https://localhost/voting/results:
   ```bash
   docker compose exec web flask --app run close-polls
   docker compose exec web flask --app run count-votes
   ```

Current demo values (hard-coded for now): the session ends after **60 seconds** idle (**10 seconds** on the update-details page), and **3 wrong passwords** within a minute lock the account for **5 seconds**.

### Useful commands

| What | Command |
| --- | --- |
| Check the audit log's hash chain (Req 9) | `docker compose exec web flask --app run verify-audit` |
| Encrypted database backup (Req 11) | `docker compose run --rm backup` (files go to `backups/`) |
| Show that voter details are stored encrypted (Req 8) | `docker compose exec db psql -U evoting evoting -c "SELECT full_name, address FROM voter_records;"` |
| Show the audit log (Req 9) | `docker compose exec db psql -U evoting evoting -c "SELECT entry_id, event_type, actor_id, prev_hash FROM audit_log;"` |
| Follow the app's logs | `docker compose logs -f web` |
| Health check (Req 22) | `curl -k https://localhost/health` |
| Crash a count partway, then resume it (Req 19). Use instead of the first plain `count-votes`; needs at least 3 ballots | `docker compose exec web flask --app run count-votes --batch-size 1 --crash-after 2`, then run `count-votes` again |
| Tamper with the saved count (Req 19). The results page then withholds the results, and the next `count-votes` detects the change and recounts | `docker compose exec db psql -U evoting evoting -c "UPDATE count_checkpoints SET ballots_counted = ballots_counted + 100;"` |

## Run without Docker (development only)

This uses SQLite (`instance/dev.db`), plain HTTP and the built-in development keys, so use it for quick checks, not the demo. Use Python 3.11 or 3.12 (`psycopg2-binary` 2.9.9 won't install on 3.13).

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Then open http://localhost:5000/auth/login. Delete `instance/dev.db` to start with an empty database. Load the electoral roll first with `flask --app run import-roll data/sample_electoral_roll.csv`.

## Tests

```bash
pytest
```

This runs `tests/` and `app/storage/test_storage.py` on throwaway SQLite databases, so Docker isn't needed.

## Which database?

**PostgreSQL** is the database the system uses. `docker compose` runs it and the app connects to it through `DATABASE_URL`. SQLite is only used when `DATABASE_URL` isn't set (running `python run.py` directly) and in the tests.

`app/storage/storage.py` takes a SQLite connection so its own unit tests run without a server. In the app, the same encryption and hash-chaining code runs on PostgreSQL through `app/storage/integration.py`.

## Project structure

```
app/
  auth/            login, two-factor (TOTP), lockout, session timeout, login log, last login
  registration/    enrolment, electoral roll check (eligibility.py), duplicate check, update details
  voting/          one-time ballot tokens, one vote per voter, anonymous ballots, HTTPS only,
                   ballot validation (validation.py), checkpointed count and results (counting.py)
  audit/           registration change history
  storage/         storage.py (Req 8–11), integration.py (connects it to the app),
                   backup.py + backup.Dockerfile (encrypted pg_dump)
  email_service.py change notification email (Req 13)
  templates/, static/
nginx/             TLS reverse proxy (Req 6)
initdb/            SQL that runs when PostgreSQL is first created (empty; Req 21 roles go here)
tests/             pytest tests
voting_security_prototype.py   earlier command-line prototype of Req 12–15
```

## Requirements checklist (22)

### Authentication
- [x] #1 — MFA (password + second factor) on every login — High / High
- [ ] #2 — Lock account 15 min after 5 failed attempts in 10 min — High / Medium *(partial: demo values hard-coded)*
- [ ] #3 — Auto session timeout after 15 min inactivity — Medium / Low *(partial: 60 s hard-coded)*
- [x] #4 — Log all login attempts (user ID, timestamp, IP, outcome) — High / Medium
- [x] #12 — Show last successful login on sign-in — Low / Low
- [x] #14 — Security reminder on login page — Low / Low
- [x] #16 — Mask password input, optional show-toggle — Low / Low

### Registration
- [x] #5 — Duplicate registration check — High / Medium
- [x] #13 — Email voter when registration details change — Low / Low
- [x] #15 — Voter can view read-only history of own record changes — Low / Medium
- [ ] #20 — Verify eligibility against electoral roll before registering — Medium / Low *(partial: age check only)*
- [ ] #21 — DB-level roles (Postgres `CREATE ROLE`/`GRANT`) — Medium / Medium
- [ ] #22 — Health-check endpoint + auto-restart on failure — Medium / Medium *(partial: `/health` + restart on crash)*

### Voting
- [x] #6 — Encrypt ballot in transit (TLS) — High / High
- [x] #7 — One vote per voter, reject repeat submissions — High / Medium
- [ ] #17 — Validate House ballot (sequential 1..N, no gaps/dupes) — Medium / Medium
- [ ] #18 — Validate Senate ballot (ATL/BTL rules, preference precedence) — High / High
- [ ] #19 — Checkpointed state machine for vote-count recovery — Medium / High

### Storage
- [x] #8 — Encrypt elector PII at rest (AES-256) — High / High
- [x] #9 — Tamper-evident audit log via hash chaining — High / High
- [x] #10 — Ballots stored decoupled from elector identity (no FK/IP/timestamp linking voter to ballot) — High / High
- [x] #11 — Encrypted point-in-time DB snapshots with SHA-256 checksum — High / High

**Complexity tally:** High 8 · Medium 8 · Low 6 (meets the ≥8 High / ≥8 Medium rule)

### How storage works in the app (Req 8–11)
- **#8** — voter name, address and date of birth, and the change history, are stored AES-256-GCM encrypted with `AES_KEY`.
- **#9** — logins, registrations and detail changes go into the hash-chained `audit_log`, and the database refuses UPDATE, DELETE and TRUNCATE on it. Votes are deliberately not logged, to protect the secret ballot.
- **#10** — the voting module stores ballots with no voter ID, IP address or timestamp.
- **#11** — `docker compose run --rm backup` writes an encrypted `pg_dump` plus its `.sha256` checksum.

## Still to do
- [ ] Req 17–19 (not in this branch yet)
- [ ] Req 21: least-privilege PostgreSQL roles in `initdb/`
- [ ] CSRF protection (Flask-WTF) and rate limiting (Flask-Limiter) on forms
- [ ] CI workflow in `.github/workflows/`
- [ ] `.dockerignore`, so `.env` isn't copied into the image

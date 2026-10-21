# Electronic Voting Platform — Security Prototype

INTE2667 Assignment 3 (Group 37). A Flask web app covering the **Authentication, Registration, Voting and Storage** subsystems of the Electronic Voting Platform, built around 22 security requirements. The voting features are kept basic; the security controls are the point.

**Stack:** Python 3.11 / Flask (served by gunicorn) · PostgreSQL 16 · nginx (TLS) · Docker Compose · GitHub Actions CI

## Run it with Docker

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/).

1. Create your `.env` from the template:
   ```bash
   cp .env.example .env
   ```
   Fill in the required values: `SECRET_KEY`, `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `APP_DB_PASSWORD` and `AES_KEY`. Generate each one with:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   The timing settings (see [Demo timings](#demo-timings)) and the `MAIL_*` settings (Req 13 email) are optional.
2. Build and start everything:
   ```bash
   docker compose up --build
   ```
   On every start the `admin` service creates any missing tables and the web app's database role (Req 21), then exits, so `admin exited with code 0` in the log is expected.
3. Open **https://localhost/auth/login**. The first start creates a self-signed certificate, so the browser warns once; accept it for the demo. Plain `http://` is redirected to HTTPS.

Stop with `Ctrl+C` (or `docker compose down`). To wipe the database and start clean, run `docker compose down -v`. Do this between demo rehearsals, because closing the polls can't be undone, and after changing `AES_KEY`, because data encrypted with the old key can't be read with the new one.

## Demo walkthrough

1. **Load the electoral roll** (Req 20). Only people on the roll can register:
   ```bash
   docker compose run --rm admin flask --app run import-roll data/sample_electoral_roll.csv
   ```
   The people in `data/sample_electoral_roll.csv` are made up. Register as one of them, using the same name, date of birth and ID number. Morgan Lee is marked not eligible, and anyone not on the roll is refused.
2. **Register** (link on the login page) and scan the QR code with Google or Microsoft Authenticator. The QR code is only shown once. One phone can hold an account for each demo voter.
3. **Log in** with your username and password, then the 6-digit code. Wrong passwords or wrong codes lock the account (Req 2).
4. From the home page:
   - **Cast your vote.** The ballot has a House paper (number every box, Req 17) and a Senate paper (at least 6 boxes above the line or 12 below, Req 18). The server refuses an informal ballot without using it up, so the voter can fix it and resubmit. A second vote is refused (Req 7).
   - **Update your registration details** (Req 13 email) and **view the change history** (Req 15).
   - **Log out**, then log in as the next voter.
5. **Close the polls and count the votes** (Req 19), then open https://localhost/voting/results:
   ```bash
   docker compose run --rm admin flask --app run close-polls
   docker compose run --rm admin flask --app run count-votes
   ```
   To show crash recovery instead, run the count with `--batch-size 1 --crash-after 2` first, then run `count-votes` again. This needs at least 3 ballots.

### Demo timings

Req 2 and 3 use the report's values unless `.env` sets shorter ones:

| Setting | Report value (default) | Demo value |
| --- | --- | --- |
| `SESSION_TIMEOUT_SECONDS`: idle time before the session ends | 900 (15 minutes) | 60 |
| `LOCKOUT_MAX_ATTEMPTS`: failed passwords or codes that lock the account | 5 | 3 |
| `LOCKOUT_WINDOW_SECONDS`: period those failures are counted over | 600 (10 minutes) | 60 |
| `LOCKOUT_SECONDS`: how long the account stays locked | 900 (15 minutes) | 5 |

Leave them blank in `.env` to use the report's values.

## Useful commands

Election officials' commands (`import-roll`, `close-polls`, `count-votes`) run in the `admin` container, which logs in as the database owner. The web app logs in as `evoting_app`, which can only do what `app/security/db_roles.py` grants (Req 21).

| What | Command |
| --- | --- |
| Check the audit log's hash chain (Req 9) | `docker compose exec web flask --app run verify-audit` |
| Show the audit log (Req 9) | `docker compose exec db psql -U evoting evoting -c "SELECT entry_id, event_type, actor_id, prev_hash FROM audit_log;"` |
| Show that voter details are stored encrypted (Req 8) | `docker compose exec db psql -U evoting evoting -c "SELECT full_name, address FROM voter_records;"` |
| Encrypted database backup (Req 11) | `docker compose run --rm backup` (files go to `backups/`) |
| The web app's database login is refused anything outside its role (Req 21) | `docker compose exec db psql -U evoting_app evoting -c "DELETE FROM audit_log;"` gives `permission denied`. So does `SELECT * FROM ballots;` |
| Tamper with the saved count (Req 19). The results page then withholds the results, and the next `count-votes` detects the change and recounts | `docker compose exec db psql -U evoting evoting -c "UPDATE count_checkpoints SET ballots_counted = ballots_counted + 100;"` |
| Health check (Req 22). Returns 503 if the database is unreachable | `curl -k https://localhost/health` |
| Crash the app and watch Docker restart it (Req 22) | `docker compose exec web kill -INT 1`, then `docker compose ps` |
| Follow the app's logs | `docker compose logs -f web` |

## Security requirements

| # | Requirement | Priority / Complexity | How it is implemented | Main code |
| --- | --- | --- | --- | --- |
| 1 | Two-factor authentication | High / High | Password, then a time-based code from an authenticator app (TOTP) | `app/auth/routes.py` |
| 2 | Lock the account after repeated failures | High / Medium | Wrong passwords and wrong codes both count, so codes can't be guessed either. See [Demo timings](#demo-timings) | `app/auth/routes.py` |
| 3 | End inactive sessions | Medium / Low | Checked on the server for every protected page, and the page returns to the login screen when idle. Also a Log out button | `app/auth/session_guard.py`, `app/static/js/session_timeout.js` |
| 4 | Log every login attempt | High / Medium | User, time, real client IP and outcome; also written to the audit log. The web app can only add log entries, not change them | `app/auth/models/login_attempt.py` |
| 5 | Stop duplicate registrations | High / Medium | Unique, cleaned-up ID number enforced by the database, and an error that doesn't say which detail matched | `app/registration/routes.py` |
| 6 | Encrypt traffic (TLS) | High / High | nginx with TLS 1.2/1.3 only, HTTP redirected to HTTPS, HSTS; voting requests that didn't arrive over HTTPS are refused | `nginx/default.conf` |
| 7 | One vote per voter | High / Medium | A one-time ballot token plus a "has voted" record with a unique constraint, used up in the same transaction as the ballot is saved | `app/voting/routes.py`, `app/voting/models.py` |
| 8 | Encrypt personal details at rest | High / High | AES-256-GCM for name, address, date of birth, the change history and the electoral roll | `app/storage/storage.py`, `app/storage/integration.py` |
| 9 | Tamper-evident audit log | High / High | SHA-256 hash chain; a database trigger blocks UPDATE, DELETE and TRUNCATE. Votes are deliberately not logged, to protect the secret ballot | `app/storage/integration.py` |
| 10 | Ballots can't be linked to voters | High / High | The ballots table has no voter ID, IP address or timestamp, and random IDs. The web app can add ballots but not read them | `app/voting/models.py` |
| 11 | Encrypted backups with checksums | High / High | `pg_dump` snapshot encrypted with AES-256-GCM, plus a SHA-256 checksum file | `app/storage/backup.py` |
| 12 | Show the last successful login | Low / Low | Shown on the home page in the voter's local time | `app/auth/routes.py`, `app/templates/home.html` |
| 13 | Email the voter when details change | Low / Low | Sent after the change is saved; the change still stands if the email fails | `app/email_service.py` |
| 14 | Security reminder on the login page | Low / Low | Fixed reminder not to share passwords or codes | `app/templates/login.html` |
| 15 | Read-only change history | Low / Medium | Each voter sees only their own history; old and new values are encrypted | `app/audit/` |
| 16 | Mask the password, with a show toggle | Low / Low | Standard password field; the toggle hides it again after 10 seconds | `app/static/js/password_toggle.js` |
| 17 | Validate House ballots on the server | Medium / Medium | Every box numbered 1 to N with no duplicates or gaps; anything but whole numbers is refused | `app/voting/validation.py` |
| 18 | Validate Senate ballots on the server | High / High | At least 6 boxes above the line or 12 below; a formal below-the-line vote takes precedence if both are filled in | `app/voting/validation.py` |
| 19 | Checkpointed, resumable count | Medium / High | Runs once the polls close. Saves totals and position together after each batch, signed with HMAC-SHA256; resumes after a crash, and recounts if a checkpoint was edited. Results come from a full preferential count | `app/voting/counting.py` |
| 20 | Check eligibility before registration | Medium / Low | ID number, name and date of birth must match an eligible entry on the electoral roll; if the roll can't be read, registration is refused | `app/registration/eligibility.py` |
| 21 | Least-privilege database roles | Medium / Medium | The web app logs in as `evoting_app` with per-table grants: logs are append-only, ballots are write-only, the roll, polls and count are read-only | `app/security/db_roles.py` |
| 22 | Health check and automatic recovery | Medium / Medium | `/health` also checks the database. After 3 failed checks in a row, Docker's healthcheck interrupts the app and the restart policy starts it again | `app/__init__.py`, `docker-compose.yml` |

**Complexity tally:** High 8 · Medium 8 · Low 6 (meets the rule of at least 8 High and 8 Medium).

### Other protections

- **No secrets in the images.** `.dockerignore` keeps `.env` and `.git` out of the containers, so the web container never holds the database owner's password.
- **No development keys in the real deployment.** Behind the TLS proxy the app refuses to start unless `SECRET_KEY`, `JWT_SECRET_KEY` and `AES_KEY` are set, and Docker Compose requires them too.
- **Cookies and headers.** The session cookie is HTTPS-only, hidden from scripts and not sent with cross-site form posts (`SameSite=Lax`). nginx also sends `X-Frame-Options: DENY` (no clickjacking), `X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`.
- **Production web server.** The app runs under gunicorn instead of Flask's development server.

## Tests and CI

```bash
pytest
```

This runs `tests/` and `app/storage/test_storage.py` on throwaway SQLite databases, so Docker isn't needed. GitHub Actions (`.github/workflows/ci.yml`) runs the same tests on every push and pull request, then [Bandit](https://bandit.readthedocs.io/), a security linter for Python.

## Run without Docker (development only)

This uses SQLite (`instance/dev.db`), plain HTTP, Flask's development server and built-in development keys, so use it for quick checks, not the demo. Use Python 3.11 or 3.12 (`psycopg2-binary` 2.9.9 won't install on 3.13).

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app run import-roll data/sample_electoral_roll.csv
python run.py
```

Then open http://localhost:5000/auth/login. Delete `instance/dev.db` to start with an empty database.

## Which database?

**PostgreSQL** is the database the system uses. `docker compose` runs it, and the app connects to it through `DATABASE_URL`. SQLite is only used when `DATABASE_URL` isn't set (running `python run.py` directly) and in the tests.

`app/storage/storage.py` takes a SQLite connection so its own unit tests run without a server. In the app, the same encryption and hash-chaining code runs on PostgreSQL through `app/storage/integration.py`.

## Project structure

```
app/
  auth/            login, two-factor (TOTP), lockout, session timeout (session_guard.py),
                   login log, last login, logout
  registration/    enrolment, electoral roll check (eligibility.py), duplicate check, update details
  voting/          one-time ballot tokens, one vote per voter, anonymous ballots, HTTPS only,
                   ballot papers, validation (validation.py), checkpointed count and results (counting.py)
  audit/           registration change history
  security/        db_roles.py: the web app's least-privilege database role and `init-db`
  storage/         storage.py (Req 8–11), integration.py (connects it to the app),
                   backup.py + backup.Dockerfile (encrypted pg_dump)
  email_service.py change notification email (Req 13)
  templates/, static/
data/              sample electoral roll of made-up people (Req 20)
nginx/             TLS reverse proxy (Req 6)
tests/             pytest tests
.github/workflows/ CI: tests and Bandit on every push and pull request
docker-compose.yml proxy (nginx), web (the app, as evoting_app), admin (setup and officials'
                   commands, as the database owner), db (PostgreSQL), backup
```

## Assumptions and limitations

- One election (`FED2026`) with made-up House candidates and Senate groups.
- Ballot rules are strict: the "savings" provisions that let some imperfect paper ballots count are not applied, because the online form can tell the voter exactly what to fix before anything is stored.
- The House count is a full preferential count. The Senate shows first preferences by group; a full Senate quota count is outside the prototype.
- Polls are closed and votes counted by an election official from the command line. There is no web interface for officials.
- Eligibility is checked against a local copy of the electoral roll, loaded from a CSV file. A real system would query the official enrolment service instead.
- The certificate is self-signed for the demo. A real deployment would use one from a certificate authority, such as Let's Encrypt.
- Email (Req 13) needs the `MAIL_*` settings. Without them the change is still saved, and the voter is told the email could not be sent.
- Docker restarts a failed app on the same machine. Alerting the team through an external uptime monitor is the production step; it can't reach `localhost`.

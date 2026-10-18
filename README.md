# Electronic Voting Platform — Security Prototype
Just a skeleton for now.

Flask + PostgreSQL + Docker.

Scope: Authentication, Registration, Voting and Storage

```
cp .env.example .env   # fill in real values
docker-compose up --build
```

Then open **https://localhost** (Req 6). nginx (`nginx/`) serves the app over
TLS 1.2/1.3 with HSTS and redirects `http://` to `https://`; the app's own port
is not published. The first start creates a self-signed certificate, so the
browser warns once: accept it for the demo. (If you add that certificate to
your keychain, browsers will remember HSTS for `localhost` for a year.)

Health check: `GET /health`

## Structure

```
app/
  auth/         -> login, MFA, lockout, session, RBAC, login history
  registration/ -> voter enrolment / record CRUD, eligibility check
  voting/       -> ballot submission, one-vote-per-voter, House/Senate validation
  audit/        -> tamper-evident audit log
  reports/      -> health/availability, aggregated reporting
  security/     -> shared helpers (hashing, encryption, TOTP) — empty so far
  models.py     -> DB models — only a placeholder User model exists
tests/          -> one placeholder test, needs real coverage
initdb/         -> DB init SQL (schema, Postgres roles/grants) goes here
```

## Requirements checklist (22)

### Authentication
- [ ] #1 — MFA (password + second factor) on every login — High / High
- [ ] #2 — Lock account 15 min after 5 failed attempts in 10 min — High / Medium
- [ ] #3 — Auto session timeout after 15 min inactivity — Medium / Low
- [ ] #4 — Log all login attempts (user ID, timestamp, IP, outcome) — High / Medium
- [ ] #12 — Show last successful login on sign-in — Low / Low
- [ ] #14 — Security reminder on login page — Low / Low
- [x] #16 — Mask password input, optional show-toggle — Low / Low

### Registration
- [ ] #5 — Duplicate registration check — High / Medium
- [ ] #13 - Email voter when registration details change — Low / Low
- [ ] #15 — Voter can view read-only history of own record changes — Low / Medium
- [ ] #20 — Verify eligibility against electoral roll before registering — Medium / Low
- [ ] #21 — DB-level roles (Postgres `CREATE ROLE`/`GRANT`, not MySQL syntax) — Medium / Medium
- [ ] #22 — Health-check endpoint + auto-restart on failure — Medium / Medium

### Voting
- [x] #6 — Encrypt ballot in transit (TLS) — High / High
- [x] #7 — One vote per voter, reject repeat submissions — High / Medium
- [ ] #17 — Validate House ballot (sequential 1..N, no gaps/dupes) — Medium / Medium
- [ ] #18 — Validate Senate ballot (ATL/BTL rules, preference precedence) — High / High
- [ ] #19 — Checkpointed state machine for vote-count recovery — Medium / High *(Counting-adjacent — confirm scope)*

### Storage
- [ ] #8 — Encrypt elector PII at rest (AES-256) — High / High
- [ ] #9 — Tamper-evident audit log via hash chaining — High / High
- [ ] #10 — Ballots stored decoupled from elector identity (no FK/IP/timestamp linking voter to ballot) — High / High
- [ ] #11 — Encrypted point-in-time DB snapshots with SHA-256 checksum — High / High

**Complexity tally:** High 8 · Medium 10 · Low 6 (meets the ≥8 High / ≥8 Medium rule)

## Security utilities (`app/security/`)
- [ ] `hashing.py` — password hashing helpers (bcrypt)
- [ ] `encryption.py` — AES-GCM encrypt/decrypt for PII / ballot isolation
- [ ] `totp.py` — MFA helpers (pyotp)
- [ ] `audit_hash.py` — hash-chaining helpers for the tamper-evident log

## Database
- [ ] Real models: User, VoterRecord, Ballot (no elector FK), AuditLog (hash-chained)
- [ ] `initdb/` SQL: schema + Postgres roles/grants (see #21 note above — Postgres syntax, not MySQL)
- [ ] Backup/snapshot script for #11 (encrypted dump + SHA-256 checksum)

## Infra
- [ ] CI (`.github/workflows/ci.yml`) already runs pytest on push — keep it green
- [ ] Rate limiting (Flask-Limiter) on auth endpoints
- [ ] CSRF (Flask-WTF) on any form-based routes
- [x] TLS for #6 — nginx reverse proxy in `nginx/`


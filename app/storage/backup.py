"""
backup.py - Req 11 for the app's PostgreSQL database.

pg_dump takes a consistent point-in-time snapshot while the app keeps running.
storage.write_encrypted_snapshot() then encrypts it with AES-256-GCM (key from
AES_KEY) and writes the SHA-256 checksum file next to it.

Run from the repo root:   docker compose run --rm backup
Output:                   backups/<timestamp>.db.enc and <timestamp>.db.enc.sha256
"""
import os
import subprocess
import sys

from storage import verify_snapshot_checksum, write_encrypted_snapshot

dump = subprocess.run(
    ["pg_dump"],
    env={"PGHOST": "db", "PGUSER": "evoting", "PGDATABASE": "evoting",
         **os.environ, "PGPASSWORD": os.environ["POSTGRES_PASSWORD"]},
    stdout=subprocess.PIPE,
    check=True,
).stdout

snapshot = write_encrypted_snapshot(dump, os.environ.get("BACKUP_DIR", "/backups"))
ok, message = verify_snapshot_checksum(snapshot["snapshot_file"], snapshot["checksum_file"])
print(f"{os.path.basename(snapshot['snapshot_file'])}  sha256={snapshot['sha256']}  checksum {message}")
sys.exit(0 if ok else 1)

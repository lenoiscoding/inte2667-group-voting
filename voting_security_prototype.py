"""
Electronic Voting Platform - Requirements 12 to 15
A small command-line prototype using Python and SQLite.

Run:
    python voting_security_prototype.py

Demo login:
    Voter ID: V001
    Password: Vote123!

Email is simulated in this prototype: the notification is saved in SQLite
and printed to the screen. No email account or password is required.
"""

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from getpass import getpass

DB_FILE = Path(__file__).with_name("voting_prototype.db")
SECURITY_REMINDER = "Never share your password or one-time verification code with anyone."


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def connect():
    db = sqlite3.connect(DB_FILE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def password_hash(password):
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
    ).hex()
    return f"{salt}${hashed}"


def password_matches(password, stored_hash):
    try:
        salt, expected = stored_hash.split("$", 1)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000
    ).hex()
    return secrets.compare_digest(actual, expected)


def setup_database():
    with connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS voters (
                voter_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                last_successful_login TEXT
            );

            CREATE TABLE IF NOT EXISTS registration_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                voter_id TEXT NOT NULL,
                field_changed TEXT NOT NULL,
                old_value TEXT NOT NULL,
                new_value TEXT NOT NULL,
                changed_at TEXT NOT NULL,
                FOREIGN KEY (voter_id) REFERENCES voters(voter_id)
            );

            CREATE TABLE IF NOT EXISTS notification_log (
                notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                voter_id TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (voter_id) REFERENCES voters(voter_id)
            );
        """)

        # Add a demo voter only if the database does not already contain one.
        db.execute("""
            INSERT OR IGNORE INTO voters
            (voter_id, name, address, email, password_hash)
            VALUES (?, ?, ?, ?, ?)
        """, ("V001", "Alex Taylor", "10 Sample Street", "alex@example.com",
              password_hash("Vote123!")))


def login():
    print("\n--- Voter login ---")
    voter_id = input("Voter ID: ").strip()
    password = getpass("Password: ")

    with connect() as db:
        voter = db.execute(
            "SELECT * FROM voters WHERE voter_id = ?", (voter_id,)
        ).fetchone()

        if not voter or not password_matches(password, voter["password_hash"]):
            print("Login failed. Check your voter ID and password.")
            return None

        previous_login = voter["last_successful_login"]
        db.execute(
            "UPDATE voters SET last_successful_login = ? WHERE voter_id = ?",
            (now(), voter_id)
        )

    print(f"\nWelcome, {voter['name']}!")
    if previous_login:
        print(f"Your previous successful login was: {previous_login}")
    else:
        print("This is your first recorded successful login.")

    # Requirement 14: show the reminder after successful login.
    print(f"\nSecurity reminder: {SECURITY_REMINDER}")
    return voter_id


def change_registration(voter_id):
    print("\n--- Update registration details ---")
    print("1. Change name")
    print("2. Change address")
    choice = input("Choose 1 or 2: ").strip()

    field = {"1": "name", "2": "address"}.get(choice)
    if not field:
        print("Invalid choice.")
        return

    new_value = input(f"Enter your new {field}: ").strip()
    if not new_value:
        print("The value cannot be empty.")
        return

    with connect() as db:
        voter = db.execute(
            f"SELECT {field}, email FROM voters WHERE voter_id = ?",
            (voter_id,)
        ).fetchone()

        old_value = voter[field]
        if old_value == new_value:
            print("No change made.")
            return

        changed_at = now()
        db.execute(
            f"UPDATE voters SET {field} = ? WHERE voter_id = ?",
            (new_value, voter_id)
        )
        db.execute("""
            INSERT INTO registration_history
            (voter_id, field_changed, old_value, new_value, changed_at)
            VALUES (?, ?, ?, ?, ?)
        """, (voter_id, field, old_value, new_value, changed_at))

        message = (
            f"Your voting-platform registration {field} was changed "
            f"on {changed_at}. If you did not make this change, contact support."
        )
        db.execute("""
            INSERT INTO notification_log
            (voter_id, message, created_at, status)
            VALUES (?, ?, ?, ?)
        """, (voter_id, message, changed_at, "SIMULATED"))

        email = voter["email"]

    print("Registration details updated.")
    print(f"\n[DEMO EMAIL to {email}]")
    print(message)
    print("(This prototype simulates email; it does not send a real email.)")


def view_history(voter_id):
    # The history query is restricted to the currently logged-in voter.
    with connect() as db:
        rows = db.execute("""
            SELECT field_changed, old_value, new_value, changed_at
            FROM registration_history
            WHERE voter_id = ?
            ORDER BY history_id DESC
        """, (voter_id,)).fetchall()

    print("\n--- Your registration change history (read-only) ---")
    if not rows:
        print("No registration changes have been recorded.")
        return

    for row in rows:
        print(f"{row['changed_at']} | {row['field_changed']}: "
              f"{row['old_value']} -> {row['new_value']}")


def voter_menu(voter_id):
    while True:
        print("\n--- Voter menu ---")
        print("1. Update my name or address")
        print("2. View my registration history")
        print("3. Log out")
        choice = input("Choose 1, 2, or 3: ").strip()

        if choice == "1":
            change_registration(voter_id)
        elif choice == "2":
            view_history(voter_id)
        elif choice == "3":
            print("Logged out.")
            return
        else:
            print("Invalid choice. Please try again.")


def main():
    setup_database()
    print("Electronic Voting Platform - Security Requirements 12-15")
    print("Demo account: V001 / Vote123!")
    print(f"\n{SECURITY_REMINDER}")

    while True:
        voter_id = login()
        if voter_id:
            voter_menu(voter_id)
        again = input("\nTry another login? (y/n): ").strip().lower()
        if again != "y":
            print("Goodbye.")
            break


if __name__ == "__main__":
    main()

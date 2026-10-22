from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from pathlib import Path
from typing import Optional, Union


# ---------------------------------------------------------------------------
# Requirement 19 - Checkpointed vote-count state machine
# ---------------------------------------------------------------------------
@dataclass
class CountState:
    job_id: str
    phase: str = "COUNTING"
    processed_ballot_ids: list[str] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)
    sequence: int = 0


class CheckpointStore:
    """SQLite checkpoint storage using atomic transactions and integrity hashes."""

    def __init__(self, database_path: Union[str, Path]) -> None:
        self.database_path = str(database_path)
        self._init_database()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _init_database(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vote_count_checkpoints (
                    job_id TEXT PRIMARY KEY,
                    sequence INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _serialize(state: CountState) -> str:
        return json.dumps(asdict(state), sort_keys=True, separators=(",", ":"))

    def save(self, state: CountState) -> None:
        state_json = self._serialize(state)
        checksum = sha256(state_json.encode("utf-8")).hexdigest()
        updated_at = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO vote_count_checkpoints(job_id, sequence, state_json, checksum, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    sequence = excluded.sequence,
                    state_json = excluded.state_json,
                    checksum = excluded.checksum,
                    updated_at = excluded.updated_at
                """,
                (state.job_id, state.sequence, state_json, checksum, updated_at),
            )
            conn.commit()

    def load(self, job_id: str) -> Optional[CountState]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state_json, checksum FROM vote_count_checkpoints WHERE job_id = ?",
                (job_id,),
            ).fetchone()

        if row is None:
            return None

        state_json, expected_checksum = row
        actual_checksum = sha256(state_json.encode("utf-8")).hexdigest()
        if actual_checksum != expected_checksum:
            raise RuntimeError("Checkpoint integrity check failed")

        data = json.loads(state_json)
        return CountState(**data)


class ResultsComputationEngine:
    """Small checkpointed state machine that can be wrapped by a larger count engine.

    The `ballot_id` makes processing idempotent: replaying a ballot after recovery
    does not increment the tally twice.
    """

    def __init__(
        self,
        job_id: str,
        store: CheckpointStore,
        checkpoint_every: int = 100,
    ) -> None:
        if checkpoint_every < 1:
            raise ValueError("checkpoint_every must be at least 1")
        self.store = store
        self.checkpoint_every = checkpoint_every
        self.state = store.load(job_id) or CountState(job_id=job_id)
        self._processed = set(self.state.processed_ballot_ids)
        self._since_checkpoint = 0

    def process_ballot(self, ballot_id: str, first_preference_candidate_id: str) -> bool:
        """Process one ballot. Returns False when it was already processed."""
        if not ballot_id:
            raise ValueError("ballot_id is required")
        if not first_preference_candidate_id:
            raise ValueError("first_preference_candidate_id is required")

        if ballot_id in self._processed:
            return False

        self.state.totals[first_preference_candidate_id] = (
            self.state.totals.get(first_preference_candidate_id, 0) + 1
        )
        self._processed.add(ballot_id)
        self.state.processed_ballot_ids.append(ballot_id)
        self.state.sequence += 1
        self._since_checkpoint += 1

        if self._since_checkpoint >= self.checkpoint_every:
            self.checkpoint()
        return True

    def checkpoint(self) -> None:
        self.store.save(self.state)
        self._since_checkpoint = 0

    def complete(self) -> CountState:
        self.state.phase = "COMPLETED"
        self.checkpoint()
        return self.state

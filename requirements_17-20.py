from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Protocol, Sequence, Union

PreferenceInput = Union[Sequence[Optional[int]], Mapping[str, Optional[int]]]


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    code: str
    message: str
    selected_method: Optional[str] = None
    normalized_preferences: tuple[int, ...] = ()


def _values(preferences: PreferenceInput) -> list[Optional[int]]:
    """Return preference values while keeping integration input flexible."""
    if isinstance(preferences, Mapping):
        return list(preferences.values())
    if isinstance(preferences, (str, bytes)):
        raise TypeError("preferences must be a sequence of integers or a mapping")
    return list(preferences)


def _clean_positive_integers(preferences: PreferenceInput) -> tuple[bool, list[int], str]:
    raw = _values(preferences)
    cleaned: list[int] = []

    for value in raw:
        if value is None or value == "":
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            return False, [], "Preferences must contain integers only."
        if value <= 0:
            return False, [], "Preference numbers must be positive integers."
        cleaned.append(value)

    return True, cleaned, ""


def _is_unbroken_sequence(values: Sequence[int], required_length: Optional[int] = None) -> bool:
    """Check for exactly one each of 1..K, with no duplicates or skipped numbers."""
    if not values:
        return False
    target_length = required_length if required_length is not None else len(values)
    return len(values) == target_length and sorted(values) == list(range(1, target_length + 1))


# ---------------------------------------------------------------------------
# Requirement 17 - House of Representatives ballot validation
# ---------------------------------------------------------------------------

def validate_house_ballot(preferences: PreferenceInput) -> ValidationResult:
    """Validate the assignment's strict House requirement.

    Every ballot position must be filled and the rankings must be exactly 1..N.
    This intentionally does not apply real-world vote-saving exceptions because the
    assignment requirement explicitly asks for no skipped numbers.
    """
    raw = _values(preferences)
    ok, cleaned, error = _clean_positive_integers(preferences)
    if not ok:
        return ValidationResult(False, "HOUSE_NON_INTEGER", error)

    if not raw:
        return ValidationResult(False, "HOUSE_EMPTY", "The House ballot is empty.")

    if len(cleaned) != len(raw):
        return ValidationResult(
            False,
            "HOUSE_MISSING_PREFERENCE",
            "Every House ballot position must contain a preference number.",
        )

    if len(set(cleaned)) != len(cleaned):
        return ValidationResult(
            False,
            "HOUSE_DUPLICATE",
            "House preference numbers cannot be duplicated.",
        )

    if not _is_unbroken_sequence(cleaned, required_length=len(raw)):
        return ValidationResult(
            False,
            "HOUSE_SEQUENCE_GAP",
            f"House preferences must form the complete sequence 1 to {len(raw)}.",
        )

    return ValidationResult(
        True,
        "HOUSE_VALID",
        "House ballot is valid.",
        selected_method="HOUSE",
        normalized_preferences=tuple(cleaned),
    )


# ---------------------------------------------------------------------------
# Requirement 18 - Senate ballot validation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SenatePolicy:
    """Configurable Senate thresholds so group members can share one validator.

    Assignment defaults are strict: ATL 1..6 and BTL 1..12.
    If your lecturer explicitly wants vote-saving thresholds, instantiate with
    atl_minimum=1 and btl_minimum=6 instead of editing the validation logic.
    """

    atl_minimum: int = 6
    btl_minimum: int = 12
    btl_precedence_when_both_valid: bool = True

    def __post_init__(self) -> None:
        if self.atl_minimum < 1 or self.btl_minimum < 1:
            raise ValueError("Senate minimums must be at least 1")


def _validate_senate_line(
    preferences: PreferenceInput,
    minimum: int,
    label: str,
) -> ValidationResult:
    ok, cleaned, error = _clean_positive_integers(preferences)
    if not ok:
        return ValidationResult(False, f"SENATE_{label}_NON_INTEGER", error)

    if not cleaned:
        return ValidationResult(False, f"SENATE_{label}_EMPTY", f"No {label} preferences supplied.")

    if len(set(cleaned)) != len(cleaned):
        return ValidationResult(
            False,
            f"SENATE_{label}_DUPLICATE",
            f"{label} preference numbers cannot be duplicated.",
        )

    # The submission is valid when it contains an unbroken sequence starting at 1
    # and that sequence reaches at least the configured minimum.
    if sorted(cleaned) != list(range(1, len(cleaned) + 1)):
        return ValidationResult(
            False,
            f"SENATE_{label}_SEQUENCE_GAP",
            f"{label} preferences must form an unbroken sequence starting at 1.",
        )

    if len(cleaned) < minimum:
        return ValidationResult(
            False,
            f"SENATE_{label}_TOO_SHORT",
            f"{label} requires at least {minimum} consecutive preferences.",
        )

    return ValidationResult(
        True,
        f"SENATE_{label}_VALID",
        f"{label} preferences are valid.",
        selected_method=label,
        normalized_preferences=tuple(cleaned),
    )


def validate_senate_ballot(
    above_the_line: PreferenceInput = (),
    below_the_line: PreferenceInput = (),
    policy: SenatePolicy = SenatePolicy(),
) -> ValidationResult:
    """Validate ATL, BTL, or dual-line Senate submissions.

    Precedence rule used here:
    1. If BTL is valid and precedence is enabled, use BTL.
    2. Otherwise, if ATL is valid, use ATL.
    3. Otherwise, if only one line was attempted, return that line's error.
    4. If both were attempted and neither is valid, reject the ballot.
    """
    atl_attempted = any(v not in (None, "") for v in _values(above_the_line))
    btl_attempted = any(v not in (None, "") for v in _values(below_the_line))

    if not atl_attempted and not btl_attempted:
        return ValidationResult(False, "SENATE_EMPTY", "No Senate preferences were supplied.")

    atl = _validate_senate_line(above_the_line, policy.atl_minimum, "ATL") if atl_attempted else None
    btl = _validate_senate_line(below_the_line, policy.btl_minimum, "BTL") if btl_attempted else None

    if atl and btl:
        if btl.valid and policy.btl_precedence_when_both_valid:
            return ValidationResult(
                True,
                "SENATE_DUAL_BTL_SELECTED",
                "Both lines were submitted; valid BTL preferences take precedence.",
                selected_method="BTL",
                normalized_preferences=btl.normalized_preferences,
            )
        if atl.valid:
            return ValidationResult(
                True,
                "SENATE_DUAL_ATL_SELECTED",
                "BTL was not valid; the valid ATL submission is used.",
                selected_method="ATL",
                normalized_preferences=atl.normalized_preferences,
            )
        if btl.valid:
            return ValidationResult(
                True,
                "SENATE_DUAL_BTL_SELECTED",
                "ATL was not valid; the valid BTL submission is used.",
                selected_method="BTL",
                normalized_preferences=btl.normalized_preferences,
            )
        return ValidationResult(
            False,
            "SENATE_DUAL_INVALID",
            f"Both Senate lines are invalid. ATL: {atl.message} BTL: {btl.message}",
        )

    return atl if atl is not None else btl  # type: ignore[return-value]


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


# ---------------------------------------------------------------------------
# Requirement 20 - Electoral eligibility before registration
# ---------------------------------------------------------------------------
class ElectoralRollRepository(Protocol):
    """Adapter contract. Another group member can implement this for any database/API."""

    def is_eligible(self, voter_id: str) -> bool:
        ...


@dataclass(frozen=True)
class RegistrationResult:
    allowed: bool
    code: str
    message: str


class VoterEligibilityService:
    def __init__(self, electoral_roll: ElectoralRollRepository) -> None:
        self.electoral_roll = electoral_roll

    def verify_before_registration(self, voter_id: str) -> RegistrationResult:
        voter_id = voter_id.strip()
        if not voter_id:
            return RegistrationResult(False, "VOTER_ID_REQUIRED", "A voter identifier is required.")

        try:
            eligible = self.electoral_roll.is_eligible(voter_id)
        except Exception:
            # Fail closed: an unavailable/failed authorised database must not silently
            # become an approval path.
            return RegistrationResult(
                False,
                "ELIGIBILITY_SERVICE_UNAVAILABLE",
                "Eligibility could not be verified. Registration is temporarily blocked.",
            )

        if not eligible:
            return RegistrationResult(
                False,
                "VOTER_NOT_ELIGIBLE",
                "The voter is not eligible according to the authorised enrolment database.",
            )

        return RegistrationResult(
            True,
            "VOTER_ELIGIBLE",
            "Eligibility verified. Registration may continue.",
        )


class InMemoryElectoralRoll:
    """Simple development/test adapter; replace with the group's real DB adapter."""

    def __init__(self, eligible_voter_ids: Iterable[str]) -> None:
        self._eligible = {v.strip() for v in eligible_voter_ids if v.strip()}

    def is_eligible(self, voter_id: str) -> bool:
        return voter_id in self._eligible


# ---------------------------------------------------------------------------
# Optional integration facade - one object for web/API controllers to call
# ---------------------------------------------------------------------------
class VotingAssignmentService:
    """Facade to minimise integration work with Flask/FastAPI/Django/CLI code."""

    def __init__(
        self,
        electoral_roll: ElectoralRollRepository,
        senate_policy: SenatePolicy = SenatePolicy(),
    ) -> None:
        self.eligibility = VoterEligibilityService(electoral_roll)
        self.senate_policy = senate_policy

    def validate_house(self, preferences: PreferenceInput) -> ValidationResult:
        return validate_house_ballot(preferences)

    def validate_senate(
        self,
        above_the_line: PreferenceInput = (),
        below_the_line: PreferenceInput = (),
    ) -> ValidationResult:
        return validate_senate_ballot(above_the_line, below_the_line, self.senate_policy)

    def verify_registration(self, voter_id: str) -> RegistrationResult:
        return self.eligibility.verify_before_registration(voter_id)


if __name__ == "__main__":
    # Tiny smoke demo; safe to remove when integrating into the group project.
    service = VotingAssignmentService(InMemoryElectoralRoll({"V1001", "V1002"}))
    print(service.validate_house([2, 1, 3]))
    print(service.validate_senate([1, 2, 3, 4, 5, 6], []))
    print(service.verify_registration("V1001"))

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


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

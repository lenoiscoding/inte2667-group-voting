from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Union

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

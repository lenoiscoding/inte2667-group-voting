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

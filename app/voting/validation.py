"""Req 17 and Req 18: server-side validation of House and Senate ballots.

Adapted from Sahil's validators (requirements_17-20.py on the
voting-sahil-nagwekar branch) to work on the raw text a browser submits.
The ballot form does no checking of its own: every rule is enforced here, on
the server, so editing the request or turning off JavaScript cannot get an
informal ballot stored. The vote count runs the same checks again (Req 19).

The rules are deliberately strict (no "savings" provisions): an online ballot
can tell the voter exactly what to fix before anything is stored.
"""
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

MAX_DIGITS = 3  # no ballot paper here has 1,000 boxes


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    code: str
    message: str
    method: Optional[str] = None  # "HOUSE", "ATL" or "BTL" when valid
    order: Tuple[str, ...] = ()  # box keys from first preference to last


@dataclass(frozen=True)
class SenatePolicy:
    """Minimum numbered boxes, from the Senate ballot instructions."""

    atl_minimum: int = 6
    btl_minimum: int = 12


class _NotANumber(ValueError):
    pass


def _parse(value):
    """A blank box is None. Anything other than a whole number is rejected."""
    if value is None:
        return None
    if isinstance(value, bool):  # bool is a kind of int in Python
        raise _NotANumber
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    # isascii() stops other scripts' digits, such as "²" or "٤", getting through.
    if not (text.isascii() and text.isdigit()) or len(text) > MAX_DIGITS:
        raise _NotANumber
    return int(text)


def _numbered_boxes(boxes):
    """{box: number} for the boxes that have a number in them."""
    parsed = {key: _parse(value) for key, value in boxes.items()}
    return {key: number for key, number in parsed.items() if number is not None}


def _has_marks(boxes):
    return any(value is not None and str(value).strip() for value in boxes.values())


def _in_order(marks):
    return tuple(sorted(marks, key=marks.get))


def validate_house_ballot(boxes: Mapping[str, object]) -> ValidationResult:
    """Req 17: every box numbered, using each number from 1 to N exactly once."""
    total = len(boxes)
    if total == 0:
        return ValidationResult(False, "HOUSE_EMPTY", "House: this ballot has no candidates.")
    try:
        marks = _numbered_boxes(boxes)
    except _NotANumber:
        return ValidationResult(False, "HOUSE_NOT_A_NUMBER", "House: use whole numbers only.")
    numbers = list(marks.values())
    if len(numbers) != total:
        return ValidationResult(
            False, "HOUSE_MISSING_PREFERENCE", f"House: number every box from 1 to {total}.")
    if len(set(numbers)) != total:
        return ValidationResult(
            False, "HOUSE_DUPLICATE", "House: each number can be used only once.")
    if sorted(numbers) != list(range(1, total + 1)):
        return ValidationResult(
            False, "HOUSE_SEQUENCE_GAP",
            f"House: use the numbers 1 to {total}, with none skipped.")
    return ValidationResult(
        True, "HOUSE_VALID", "House ballot is formal.", "HOUSE", _in_order(marks))


def validate_senate_line(boxes: Mapping[str, object], minimum: int, method: str) -> ValidationResult:
    """One line of the Senate ballot: numbers 1 to K with none skipped, K >= minimum."""
    where = "above the line" if method == "ATL" else "below the line"
    try:
        marks = _numbered_boxes(boxes)
    except _NotANumber:
        return ValidationResult(
            False, f"SENATE_{method}_NOT_A_NUMBER", f"Senate {where}: use whole numbers only.")
    numbers = list(marks.values())
    if not numbers:
        return ValidationResult(
            False, f"SENATE_{method}_EMPTY", f"Senate {where}: no boxes are numbered.")
    if len(set(numbers)) != len(numbers):
        return ValidationResult(
            False, f"SENATE_{method}_DUPLICATE",
            f"Senate {where}: each number can be used only once.")
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        return ValidationResult(
            False, f"SENATE_{method}_SEQUENCE_GAP",
            f"Senate {where}: number the boxes from 1 upwards, with none skipped.")
    if len(numbers) < minimum:
        return ValidationResult(
            False, f"SENATE_{method}_TOO_SHORT",
            f"Senate {where}: number at least {minimum} boxes (you numbered {len(numbers)}).")
    return ValidationResult(
        True, f"SENATE_{method}_VALID", f"Senate {where} is formal.", method, _in_order(marks))


def validate_senate_ballot(atl_boxes, btl_boxes, policy=SenatePolicy()) -> ValidationResult:
    """Req 18: a vote above the line, below the line, or both.

    When both lines are filled in, a formal below-the-line vote takes
    precedence; if it is not formal, a formal above-the-line vote is used.
    """
    atl = validate_senate_line(atl_boxes, policy.atl_minimum, "ATL") if _has_marks(atl_boxes) else None
    btl = validate_senate_line(btl_boxes, policy.btl_minimum, "BTL") if _has_marks(btl_boxes) else None

    if atl is None and btl is None:
        return ValidationResult(
            False, "SENATE_EMPTY",
            f"Senate: number at least {policy.atl_minimum} boxes above the line "
            f"or at least {policy.btl_minimum} boxes below the line.")
    if atl is None:
        return btl
    if btl is None:
        return atl
    if btl.valid:
        return ValidationResult(
            True, "SENATE_DUAL_BTL_USED",
            "You filled in both parts of the Senate ballot, so your below-the-line "
            "vote was used (it takes precedence).", "BTL", btl.order)
    if atl.valid:
        return ValidationResult(
            True, "SENATE_DUAL_ATL_USED",
            "Your below-the-line numbering was not formal, so your above-the-line "
            "vote was used.", "ATL", atl.order)
    return ValidationResult(False, "SENATE_DUAL_INVALID", f"{atl.message} {btl.message}")

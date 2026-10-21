"""Req 17 and 18: House and Senate ballots are validated on the server."""
import json

import pytest

from app.voting.ballot_papers import HOUSE_CANDIDATES, SENATE_CANDIDATES, SENATE_GROUPS
from app.voting.models import Ballot
from app.voting.validation import validate_house_ballot, validate_senate_ballot
from tests.test_voting import FULL_BALLOT, cast, open_ballot, voter  # noqa: F401 (fixture)

GROUPS = [group["code"] for group in SENATE_GROUPS]  # 7 boxes above the line
CANDIDATES = list(SENATE_CANDIDATES)  # 14 boxes below the line
ATL_6 = [str(n) for n in range(1, 7)]
BTL_12 = [str(n) for n in range(1, 13)]


def house(*numbers):
    return validate_house_ballot(dict(zip(HOUSE_CANDIDATES, numbers)))


def boxes(keys, numbers):
    """Fill the first boxes in order and leave the rest blank."""
    return {key: numbers[i] if i < len(numbers) else "" for i, key in enumerate(keys)}


def senate(atl=(), btl=()):
    return validate_senate_ballot(boxes(GROUPS, list(atl)), boxes(CANDIDATES, list(btl)))


# Req 17: House of Representatives -------------------------------------------

def test_house_accepts_every_box_numbered_1_to_n():
    result = house("2", "1", "4", "3")
    assert result.valid
    assert result.order == ("Jordan Lee", "Avery Brooks", "Sam Walker", "Priya Nair")


@pytest.mark.parametrize("numbers, code", [
    (("1", "2", "3", ""), "HOUSE_MISSING_PREFERENCE"),
    (("1", "1", "2", "3"), "HOUSE_DUPLICATE"),
    (("1", "2", "3", "5"), "HOUSE_SEQUENCE_GAP"),
    (("0", "1", "2", "3"), "HOUSE_SEQUENCE_GAP"),
    (("1", "2", "3", "x"), "HOUSE_NOT_A_NUMBER"),
    (("1", "2", "3", "-4"), "HOUSE_NOT_A_NUMBER"),
    (("1", "2", "3", "4.0"), "HOUSE_NOT_A_NUMBER"),
    (("1", "2", "3", "٤"), "HOUSE_NOT_A_NUMBER"),  # an Arabic-Indic 4
])
def test_house_rejects_informal_ballots(numbers, code):
    result = house(*numbers)
    assert not result.valid and result.code == code


# Req 18: Senate ----------------------------------------------------------------

def test_senate_above_the_line_needs_at_least_6():
    result = senate(atl=ATL_6)
    assert result.valid and result.method == "ATL" and result.order[0] == "A"


def test_senate_below_the_line_needs_at_least_12():
    result = senate(btl=BTL_12)
    assert result.valid and result.method == "BTL" and len(result.order) == 12


@pytest.mark.parametrize("atl, btl, code", [
    ((), (), "SENATE_EMPTY"),
    (ATL_6[:5], (), "SENATE_ATL_TOO_SHORT"),
    ((), BTL_12[:11], "SENATE_BTL_TOO_SHORT"),
    (["1", "2", "3", "4", "5", "7"], (), "SENATE_ATL_SEQUENCE_GAP"),
    (["1", "1", "2", "3", "4", "5"], (), "SENATE_ATL_DUPLICATE"),
    (["1", "two"], (), "SENATE_ATL_NOT_A_NUMBER"),
    (ATL_6[:5], BTL_12[:11], "SENATE_DUAL_INVALID"),
])
def test_senate_rejects_informal_ballots(atl, btl, code):
    result = senate(atl, btl)
    assert not result.valid and result.code == code


def test_dual_line_below_the_line_takes_precedence():
    result = senate(atl=ATL_6, btl=BTL_12)
    assert result.valid and result.method == "BTL" and result.code == "SENATE_DUAL_BTL_USED"


def test_dual_line_falls_back_to_a_formal_vote_above_the_line():
    result = senate(atl=ATL_6, btl=BTL_12[:5])
    assert result.valid and result.method == "ATL" and result.code == "SENATE_DUAL_ATL_USED"


# Through the ballot page ---------------------------------------------------------

def test_server_rejects_an_edited_request_and_keeps_the_token(client, voter):
    token = open_ballot(client)
    edited = {**FULL_BALLOT, "pref_1": "1"}  # two first preferences
    response = cast(client, token, edited)
    assert response.status_code == 400
    assert "each number can be used only once" in response.get_data(as_text=True)
    assert Ballot.query.count() == 0
    assert cast(client, token).status_code == 200  # fixed, same token


def test_stored_ballot_holds_only_the_senate_line_that_counts(client, voter):
    below = {f"btl_{cid}": str(n) for n, cid in enumerate(CANDIDATES[:12], start=1)}
    assert cast(client, open_ballot(client), {**FULL_BALLOT, **below}).status_code == 200
    stored = json.loads(Ballot.query.one().senate_prefs)
    assert stored["method"] == "BTL" and len(stored["preferences"]) == 12

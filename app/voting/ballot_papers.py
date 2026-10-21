"""The ballot papers for the prototype's single election (Req 17 and 18).

All parties and candidates are made up for the demo.
"""
from app.voting.validation import SenatePolicy

ELECTION_ID = "FED2026"

HOUSE_CANDIDATES = ["Avery Brooks", "Jordan Lee", "Priya Nair", "Sam Walker"]

# Senate groups in ballot order. A candidate's ID is their group's code plus
# their position in the group: A1, A2, B1, ...
SENATE_GROUPS = [
    {"code": "A", "party": "Harbour Party", "candidates": ["Mia Chen", "Oliver Grant"]},
    {"code": "B", "party": "Coastal Alliance", "candidates": ["Noah Patel", "Grace Wilson"]},
    {"code": "C", "party": "Outback Voice", "candidates": ["Ethan Ross", "Chloe Martin"]},
    {"code": "D", "party": "Tech Forward", "candidates": ["Lucas Kim", "Ava Thompson"]},
    {"code": "E", "party": "Lantern Party", "candidates": ["Isla Murphy", "Jack Nguyen"]},
    {"code": "F", "party": "Riverbend Group", "candidates": ["Zoe Campbell", "Leo Fraser"]},
    {"code": "G", "party": "Summit Independents", "candidates": ["Ruby Singh", "Henry Walsh"]},
]

SENATE_CANDIDATES = {
    f"{group['code']}{position}": name
    for group in SENATE_GROUPS
    for position, name in enumerate(group["candidates"], start=1)
}
SENATE_CANDIDATE_GROUP = {candidate_id: candidate_id[0] for candidate_id in SENATE_CANDIDATES}

# Req 18: at least 6 boxes above the line, or at least 12 below it.
SENATE_POLICY = SenatePolicy(atl_minimum=6, btl_minimum=12)

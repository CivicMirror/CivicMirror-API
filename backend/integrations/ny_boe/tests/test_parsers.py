import json
from pathlib import Path


def test_validate_certification_snapshot_flags_truncated_counties():
    from integrations.ny_boe.parsers import validate_certification_snapshot

    doc = {
        "contests": [
            {
                "office": "Representative in Congress",
                "district": "19",
                "district2": "",
                "party": "Democratic",
                "counties": "Broome, Part of",
                "vote_for": "1",
                "candidates": [{"ballot_order": "1", "name": "Alex Rivera"}],
                "key": "Representative in Congress|19||Democratic",
            }
        ],
        "version_history": [{"date": "04.29.2026", "changes": ["Original version"]}],
    }

    issues = validate_certification_snapshot(doc)

    assert any("suspicious counties" in issue for issue in issues)


def test_golden_certification_json_counts_and_running_mate_gap():
    fixture = Path(__file__).resolve().parents[4] / "docs/state-research/NY/ny_cert_2026.json"
    with fixture.open() as f:
        doc = json.load(f)

    assert len(doc["contests"]) == 433
    assert sum(len(contest["candidates"]) for contest in doc["contests"]) == 1285
    assert not [
        candidate
        for contest in doc["contests"]
        for candidate in contest["candidates"]
        if "running_mate" in candidate
    ]


def test_parse_version_history_text_returns_changes_list():
    from integrations.ny_boe.parsers import parse_version_history_text

    text = """
    04.29.2026
    - Original version
    04.30.2026
    - Comptroller: Removed Litigation Pending.
    - 2nd CD: Added Litigation Pending.
    """

    assert parse_version_history_text(text) == [
        {"date": "04.29.2026", "changes": ["Original version"]},
        {
            "date": "04.30.2026",
            "changes": [
                "Comptroller: Removed Litigation Pending.",
                "2nd CD: Added Litigation Pending.",
            ],
        },
    ]

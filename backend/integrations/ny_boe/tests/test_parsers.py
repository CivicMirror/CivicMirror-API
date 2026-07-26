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


def test_parse_certification_pdf_extracts_joint_ticket_candidates():
    """Regression test for the real production bug: the two-column
    Governor/Lt. Governor joint-ticket header renders as two separate PDF rows
    ("Ballot Order" then "Candidate Name" x2), a few points apart — within
    BAND but outside ROW_TOL, so they never cluster into one row. The old
    single combined condition (`"Candidate Name" in text and "Ballot Order"
    in text`) never matched either row, so the header text and every
    following candidate name fell through into the `vote_for` continuation
    branch instead, leaving `candidates: []` for all four Governor primaries.

    Fixture: real pages 3-4 (0-indexed 2-3) of the live June 23, 2026
    certification PDF, captured while investigating issue #40/#87, trimmed to
    keep the fixture small. Contains all four Governor/Lt. Governor party
    primaries plus two single-column Comptroller primaries as a control case.
    """
    from integrations.ny_boe.parsers import parse_certification_pdf, validate_certification_snapshot

    fixture = Path(__file__).parent / "fixtures" / "ny_cert_2026_governor_pages.pdf"
    doc = parse_certification_pdf(fixture.read_bytes())

    assert validate_certification_snapshot(doc) == []

    governor_contests = {c["party"]: c for c in doc["contests"] if c["office"] == "Governor and Lt. Governor"}
    assert set(governor_contests) == {"Democratic", "Republican", "Conservative", "Working Families"}
    for party, contest in governor_contests.items():
        assert len(contest["candidates"]) == 1, f"{party} should have exactly one joint ticket"
        candidate = contest["candidates"][0]
        assert candidate["name"], f"{party} ticket missing a governor name"
        assert candidate["running_mate"], f"{party} ticket missing a running mate"

    # Single-column contests on the same pages must be unaffected by the fix.
    comptroller_dem = next(c for c in doc["contests"] if c["office"] == "Comptroller" and c["party"] == "Democratic")
    assert [c["name"] for c in comptroller_dem["candidates"]] == [
        "Thomas P. DiNapoli", "Drew Warshaw", "Raj Goyle",
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

from datetime import date
from pathlib import Path

from cm2_ma.constants import UPCOMING_ELECTIONS_URL
from cm2_ma.sources.upcoming_elections import MaUpcomingElectionsSource, parse_upcoming_elections

FIXTURES = Path(__file__).parent / "fixtures"


def test_parses_date_embedded_in_heading_and_splits_label():
    records = parse_upcoming_elections(
        (FIXTURES / "upcoming_elections_2026.html").read_bytes(),
        source_artifact_public_id="artifact/ma-upcoming-2026",
    )

    assert [(record.name, record.election_date, record.election_type) for record in records] == [
        ("State Primaries", date(2026, 9, 1), "primary"),
        ("State Election", date(2026, 11, 3), "general"),
    ]
    assert {record.source_artifact_public_id for record in records} == {"artifact/ma-upcoming-2026"}
    assert all(record.lifecycle_status == "upcoming" for record in records)


def test_headings_without_a_recognized_type_default_to_other():
    content = b"<h2>March 3, 2026 \xe2\x80\x93 Municipal Preliminary</h2><p>text</p>"

    records = parse_upcoming_elections(content)

    assert len(records) == 1
    assert records[0].election_type == "other"


def test_headings_without_a_parseable_date_are_skipped():
    content = b"<h2>Voter Dates and Deadlines</h2><ul><li>No date here</li></ul>"

    records = parse_upcoming_elections(content)

    assert records == ()


def test_source_url_and_parse_delegate_correctly():
    source = MaUpcomingElectionsSource()
    assert source.url == UPCOMING_ELECTIONS_URL

    records = source.parse((FIXTURES / "upcoming_elections_2026.html").read_bytes())
    assert len(records) == 2

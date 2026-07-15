import json
from pathlib import Path

from integrations.ga_sos.media_export import iter_media_export_rows

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_iter_media_export_rows_emits_state_rows():
    rows = list(iter_media_export_rows(_fixture("media_export_sample_06162026.json")))

    row = next(
        r for r in rows
        if r["level"] == "state" and r["contest_id"] == "US2R" and r["candidate_name"] == "Mike Collins"
    )

    assert row["county"] == ""
    assert row["precinct_id"] == ""
    assert row["contest_name"] == "US Senate - Rep"
    assert row["candidate_id"] == "2"
    assert row["party"] == "REP"
    assert row["vote_count"] == 390174
    assert row["scoped_option_id"] == "US2R:2"


def test_iter_media_export_rows_emits_county_rows():
    rows = list(iter_media_export_rows(_fixture("media_export_sample_06162026.json")))

    row = next(
        r for r in rows
        if r["level"] == "county" and r["county"] == "Appling County" and r["contest_id"] == "US2R"
        and r["candidate_name"] == "Mike Collins"
    )

    assert row["precinct_id"] == ""
    assert row["candidate_id"] == "2"
    assert row["vote_count"] == 1394
    assert row["scoped_option_id"] == "US2R:2"


def test_iter_media_export_rows_emits_precinct_rows():
    rows = list(iter_media_export_rows(_fixture("media_export_sample_06162026.json")))

    row = next(
        r for r in rows
        if r["level"] == "precinct" and r["county"] == "Appling County" and r["precinct_id"] == "1B"
        and r["contest_id"] == "US2R" and r["candidate_name"] == "Mike Collins"
    )

    assert row["precinct_name"] == "1B"
    assert row["reporting_status"] == "Fully Reported"
    assert row["vote_count"] == 197
    assert row["scoped_option_id"] == "US2R:2"

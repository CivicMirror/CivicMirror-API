from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

from elections.models import Election, Race
from integrations.or_sos.mappers import map_race
from integrations.or_sos.parsers import OrOpenOffice, parse_open_offices_text
from integrations.or_sos.tasks import sync_or_race_skeleton
from ops.models import SyncLog

_OPEN_OFFICES_TEXT = """
November 3, 2026 General Election
U.S. Senator
U.S. Representative, Districts 1-6
Governor
State Senator, Districts 1, 3, 5
State Representative, Districts 1-3
"""


def _make_election(status=Election.Status.UPCOMING):
    election = MagicMock()
    election.pk = 42
    election.source_id = "or_sos_2026_general"
    election.name = "2026 Oregon General Election"
    election.state = "OR"
    election.status = status
    election.election_date = datetime.date(2026, 11, 3)
    return election


def test_parse_open_offices_text_core_federal_and_state_races():
    offices = parse_open_offices_text(_OPEN_OFFICES_TEXT)
    titles = [office.office_title for office in offices]

    assert "U.S. Senator" in titles
    assert "Governor" in titles
    assert "U.S. Representative, District 1" in titles
    assert "U.S. Representative, District 6" in titles
    assert "Oregon State Senate, District 3" in titles
    assert "Oregon State Representative, District 3" in titles
    assert len(offices) == 14


def test_parse_open_offices_text_deduplicates_repeated_lines():
    offices = parse_open_offices_text("U.S. Senator\nU.S. Senator\n")

    assert offices == [OrOpenOffice(office_title="U.S. Senator", office_code="us_senate")]


def test_parse_open_offices_text_handles_sectioned_district_rows():
    offices = parse_open_offices_text(
        """
        US Senator
        US Representative
        1st District Clatsop County
        2nd District Baker County
        Governor
        State Senate
        3rd District Portion of Jackson County
        State Representative
        1st District Curry County
        60th District Baker County
        Nonpartisan Offices
        Judge of the Circuit Court
        2nd District, Lane County
        """
    )
    titles = [office.office_title for office in offices]

    assert titles == [
        "U.S. Senator",
        "U.S. Representative, District 1",
        "U.S. Representative, District 2",
        "Governor",
        "Oregon State Senate, District 3",
        "Oregon State Representative, District 1",
        "Oregon State Representative, District 60",
    ]


def test_map_race_for_district_office():
    election = _make_election()
    office = OrOpenOffice(
        office_title="Oregon State Representative, District 7",
        office_code="state_house",
        district="7",
        ocd_division_id="ocd-division/country:us/state:or/sldl:7",
        geography_scope="district",
    )

    mapped = map_race(election, office, "https://example.test/open-offices.pdf")

    assert mapped["race_type"] == Race.RaceType.CANDIDATE
    assert mapped["office_title"] == "Oregon State Representative, District 7"
    assert mapped["jurisdiction"] == "Oregon District 7"
    assert mapped["geography_scope"] == "district"
    assert mapped["source"] == Race.Source.OR_SOS
    assert mapped["source_links"] == ["https://example.test/open-offices.pdf"]
    assert mapped["source_metadata"]["or_sos_office_code"] == "state_house"


def test_sync_or_race_skeleton_upserts_parsed_offices():
    election = _make_election()
    sync_log = MagicMock()
    offices = [
        OrOpenOffice(office_title="U.S. Senator", office_code="us_senate"),
        OrOpenOffice(
            office_title="U.S. Representative, District 1",
            office_code="us_house",
            district="1",
            ocd_division_id="ocd-division/country:us/state:or/cd:1",
            geography_scope="district",
        ),
    ]

    with patch("integrations.or_sos.tasks.Election.objects.get", return_value=election), \
         patch("integrations.or_sos.tasks.SyncLog.objects.create", return_value=sync_log), \
         patch("integrations.or_sos.tasks.OrSosClient") as MockClient, \
         patch("integrations.or_sos.tasks.parse_open_offices_pdf", return_value=offices), \
         patch("aggregation.ingest.ingest_race") as mock_ingest:
        MockClient.return_value.fetch_open_offices_pdf.return_value = (
            b"pdf bytes",
            "https://example.test/open-offices.pdf",
        )
        mock_ingest.side_effect = [(MagicMock(), True), (MagicMock(), False)]

        result = sync_or_race_skeleton.run(election.pk)

    assert result == {"created": 1, "updated": 1, "skipped": 0}
    assert mock_ingest.call_count == 2
    first_call = mock_ingest.call_args_list[0].kwargs
    assert first_call["source"] == "or_sos"
    assert first_call["identity"]["office_title"] == "U.S. Senator"
    assert sync_log.status == SyncLog.Status.COMPLETED

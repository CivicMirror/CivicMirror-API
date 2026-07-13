from __future__ import annotations

from unittest.mock import MagicMock, patch

from elections.models import Candidate, Election, Race
from integrations.or_sos.client import OrSosClient
from integrations.or_sos.mappers import (
    map_candidate,
    map_measure_race,
    map_race_from_candidate_filing,
    normalize_orestar_office,
)
from integrations.or_sos.parsers import parse_candidate_filings, parse_local_measures
from integrations.or_sos.tasks import sync_or_candidates, sync_or_local_measures
from ops.models import SyncLog

_CANDIDATE_HTML = """
<table id="cfSearchResults">
  <tr><th>Ballot Name</th><th>Party</th><th>Office</th><th>Election</th><th>Filing Method</th><th>Filing Date</th><th>Qualified</th></tr>
  <tr><td>Jane Doe</td><td>Democrat</td><td>State Representative, 13th District</td><td>2026 General Election</td><td>Nominated</td><td>06/25/2026</td><td>Yes</td></tr>
  <tr><td>John Smith</td><td>Republican</td><td>US Representative, 5th District</td><td>2026 General Election</td><td>Nominated</td><td>06/25/2026</td><td>No</td></tr>
</table>
"""


_MEASURE_HTML = """
<table id="measSearchResults">
  <tr><th>Measure</th><th>Election</th><th>County</th><th>Ballot Title Caption</th></tr>
  <tr><td>1-135</td><td>2026 Primary Election</td><td>Baker</td><td>Renewal of 5-year local option tax for library operations</td></tr>
</table>
"""


def _candidate_html(count: int) -> str:
    rows = "".join(
        f"<tr><td>Candidate {idx}</td><td>Democrat</td><td>Governor</td><td>2026 General Election</td><td>Nominated</td><td>06/25/2026</td><td>Yes</td></tr>"
        for idx in range(count)
    )
    return (
        '<table id="cfSearchResults">'
        '<tr><th>Ballot Name</th><th>Party</th><th>Office</th><th>Election</th><th>Filing Method</th><th>Filing Date</th><th>Qualified</th></tr>'
        f"{rows}</table>"
    )


def _candidate_rows_html(names: list[str]) -> str:
    rows = "".join(
        f"<tr><td>{name}</td><td>Democrat</td><td>Governor</td><td>2026 General Election</td><td>Nominated</td><td>06/25/2026</td><td>Yes</td></tr>"
        for name in names
    )
    return (
        '<table id="cfSearchResults">'
        '<tr><th>Ballot Name</th><th>Party</th><th>Office</th><th>Election</th><th>Filing Method</th><th>Filing Date</th><th>Qualified</th></tr>'
        f"{rows}</table>"
    )


def _make_election():
    election = MagicMock()
    election.pk = 42
    election.status = Election.Status.UPCOMING
    return election


def test_parse_candidate_filings():
    rows = parse_candidate_filings(_CANDIDATE_HTML)

    assert len(rows) == 2
    assert rows[0].ballot_name == "Jane Doe"
    assert rows[0].office == "State Representative, 13th District"
    assert rows[0].qualified == "Yes"


def test_normalize_orestar_office_for_core_races():
    assert normalize_orestar_office("US Representative, 5th District") == (
        "U.S. Representative, District 5",
        "ocd-division/country:us/state:or/cd:5",
        "district",
        "5",
    )
    assert normalize_orestar_office("State Senator, 16th District")[0] == "Oregon State Senate, District 16"


def test_map_candidate_marks_unqualified_as_disqualified():
    filing = parse_candidate_filings(_CANDIDATE_HTML)[1]
    mapped = map_candidate(filing)

    assert mapped["party"] == "Republican"
    assert mapped["candidate_status"] == Candidate.CandidateStatus.DISQUALIFIED
    assert mapped["source_metadata"]["or_sos_filing_method"] == "Nominated"


def test_map_race_from_candidate_filing():
    election = _make_election()
    filing = parse_candidate_filings(_CANDIDATE_HTML)[0]
    mapped = map_race_from_candidate_filing(election, filing)

    assert mapped["race_type"] == Race.RaceType.CANDIDATE
    assert mapped["office_title"] == "Oregon State Representative, District 13"
    assert mapped["ocd_division_id"] == "ocd-division/country:us/state:or/sldl:13"


def test_parse_local_measures_and_map_measure_race():
    measure = parse_local_measures(_MEASURE_HTML)[0]
    mapped = map_measure_race(_make_election(), measure)

    assert measure.measure_number == "1-135"
    assert mapped["race_type"] == Race.RaceType.MEASURE
    assert mapped["vote_method"] == Race.VoteMethod.YES_NO
    assert mapped["jurisdiction"] == "Baker County, Oregon"


def test_sync_or_candidates_upserts_races_and_candidates():
    election = _make_election()
    sync_log = MagicMock()
    race = MagicMock()

    with patch("integrations.or_sos.tasks.Election.objects.get", return_value=election), \
         patch("integrations.or_sos.tasks.SyncLog.objects.create", return_value=sync_log), \
         patch("integrations.or_sos.tasks.OrSosClient") as MockClient, \
         patch("aggregation.ingest.ingest_race", return_value=(race, True)) as mock_race, \
         patch("aggregation.ingest.ingest_candidate", return_value=(MagicMock(), True)) as mock_candidate:
        MockClient.return_value.search_candidate_filings.side_effect = [(_CANDIDATE_HTML, "https://example.test"), ("", "")]

        result = sync_or_candidates.run(election.pk)

    assert result["filings"] == 2
    assert mock_race.call_count == 2
    assert mock_candidate.call_count == 2
    assert sync_log.status == SyncLog.Status.COMPLETED


def test_sync_or_candidates_stops_on_duplicate_page():
    election = _make_election()
    sync_log = MagicMock()
    race = MagicMock()
    page_html = _candidate_html(50)

    with patch("integrations.or_sos.tasks.Election.objects.get", return_value=election), \
         patch("integrations.or_sos.tasks.SyncLog.objects.create", return_value=sync_log), \
         patch("integrations.or_sos.tasks.OrSosClient") as MockClient, \
         patch("aggregation.ingest.ingest_race", return_value=(race, True)) as mock_race, \
         patch("aggregation.ingest.ingest_candidate", return_value=(MagicMock(), True)) as mock_candidate:
        MockClient.return_value.search_candidate_filings.side_effect = [(page_html, ""), (page_html, "")]

        result = sync_or_candidates.run(election.pk)

    assert result["filings"] == 50
    assert mock_race.call_count == 50
    assert mock_candidate.call_count == 50


def test_sync_or_candidates_skips_overlapping_page_boundary_rows():
    election = _make_election()
    sync_log = MagicMock()
    race = MagicMock()
    first_page = _candidate_rows_html([f"Candidate {idx}" for idx in range(50)])
    second_page = _candidate_rows_html(["Candidate 49", "Candidate 50"])

    with patch("integrations.or_sos.tasks.Election.objects.get", return_value=election), \
         patch("integrations.or_sos.tasks.SyncLog.objects.create", return_value=sync_log), \
         patch("integrations.or_sos.tasks.OrSosClient") as MockClient, \
         patch("aggregation.ingest.ingest_race", return_value=(race, True)) as mock_race, \
         patch("aggregation.ingest.ingest_candidate", return_value=(MagicMock(), True)) as mock_candidate:
        MockClient.return_value.search_candidate_filings.side_effect = [(first_page, ""), (second_page, "")]

        result = sync_or_candidates.run(election.pk)

    assert result["filings"] == 51
    assert mock_race.call_count == 51
    assert mock_candidate.call_count == 51


def test_sync_or_local_measures_upserts_yes_no_options():
    election = _make_election()
    sync_log = MagicMock()
    race = MagicMock()

    with patch("integrations.or_sos.tasks.Election.objects.get", return_value=election), \
         patch("integrations.or_sos.tasks.SyncLog.objects.create", return_value=sync_log), \
         patch("integrations.or_sos.tasks.OrSosClient") as MockClient, \
         patch("aggregation.ingest.ingest_race", return_value=(race, True)) as mock_race, \
         patch("integrations.or_sos.tasks.MeasureOption.objects.get_or_create") as mock_option:
        MockClient.return_value.search_local_measures.side_effect = [(_MEASURE_HTML, "https://example.test"), ("", "")]

        result = sync_or_local_measures.run(election.pk)

    assert result == {"measures": 1, "created": 1, "updated": 0}
    mock_race.assert_called_once()
    assert mock_option.call_count == 2
    assert sync_log.status == SyncLog.Status.COMPLETED


def test_orestar_candidate_client_includes_csrf_and_pagination_fields():
    client = OrSosClient()
    client.session = MagicMock()
    token_response = MagicMock(text="OWASP_CSRFTOKEN:TOKEN-123")
    result_response = MagicMock(text="<html>ok</html>", url="https://secure.sos.state.or.us/orestar/cfFilings.do")
    client.session.post.side_effect = [token_response, result_response]

    html, _ = client.search_candidate_filings(2026, "1453", page_index=1)

    assert html == "<html>ok</html>"
    token_kwargs = client.session.post.call_args_list[0].kwargs
    assert token_kwargs["headers"]["FETCH-CSRF-TOKEN"] == "1"
    post_kwargs = client.session.post.call_args_list[1].kwargs
    assert post_kwargs["data"]["OWASP_CSRFTOKEN"] == "TOKEN-123"
    assert post_kwargs["data"]["cfSearchPageIdx"] == "1"
    assert post_kwargs["data"]["cfSearchButtonName"] == "next"
    assert post_kwargs["data"]["by"] == "BALLOT_NAME"


def test_orestar_local_measure_client_includes_csrf_and_pagination_fields():
    client = OrSosClient()
    client.session = MagicMock()
    token_response = MagicMock(text="OWASP_CSRFTOKEN:TOKEN-456")
    result_response = MagicMock(text="<html>ok</html>", url="https://secure.sos.state.or.us/orestar/LocalMeasures.do")
    client.session.post.side_effect = [token_response, result_response]

    html, _ = client.search_local_measures(2026, "1451", page_index=2)

    assert html == "<html>ok</html>"
    token_kwargs = client.session.post.call_args_list[0].kwargs
    assert token_kwargs["headers"]["FETCH-CSRF-TOKEN"] == "1"
    post_kwargs = client.session.post.call_args_list[1].kwargs
    assert post_kwargs["data"]["OWASP_CSRFTOKEN"] == "TOKEN-456"
    assert post_kwargs["data"]["measSearchPageIdx"] == "2"
    assert post_kwargs["data"]["searchButtonName"] == "next"
    assert post_kwargs["data"]["by"] == "MEASURE"

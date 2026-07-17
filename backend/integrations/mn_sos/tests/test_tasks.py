import datetime
from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, ElectionSourceLink, Race
from integrations.mn_sos.election_registry import MnElection
from integrations.mn_sos.tasks import discover_mn_elections, sync_mn_races
from ops.models import SyncLog

_IN_SCOPE_FILES = [
    {"label": "U.S. Senator Statewide", "url": "https://x/ussenate.txt"},
]

_SENATE_RESULT_ROWS = [
    {
        "state": "MN", "county_id": "", "precinct_name": "", "office_id": "0102",
        "office_name": "U.S. Senator", "district": "", "candidate_order_code": "0202",
        "candidate_name": "Amy Klobuchar", "suffix": "", "incumbent_code": "",
        "party": "DFL", "precincts_reporting": "4103", "total_precincts": "4103",
        "candidate_votes": "1792441", "candidate_pct": "56.20", "total_office_votes": "3189323",
    },
    {
        "state": "MN", "county_id": "", "precinct_name": "", "office_id": "0102",
        "office_name": "U.S. Senator", "district": "", "candidate_order_code": "9901",
        "candidate_name": "WRITE-IN", "suffix": "", "incumbent_code": "",
        "party": "WI", "precincts_reporting": "4103", "total_precincts": "4103",
        "candidate_votes": "3578", "candidate_pct": "0.11", "total_office_votes": "3189323",
    },
]

_CANDIDATE_ROWS = [
    {
        "candidate_id": "01020202", "candidate_name": "Amy Klobuchar",
        "office_id": "0102", "office_title": "U.S. Senator",
        "county_id": "88", "order_code": "02", "party": "DFL",
    },
    {
        # County candidate — must be filtered out (office_id 0102 not present for this row).
        "candidate_id": "99990101", "candidate_name": "County Commissioner Person",
        "office_id": "9999", "office_title": "County Commissioner",
        "county_id": "01", "order_code": "01", "party": "",
    },
]


@pytest.mark.django_db
def test_sync_mn_races_creates_election_race_and_in_scope_candidate_only():
    with patch(
        "integrations.mn_sos.tasks.probe_in_scope_files",
        return_value=_IN_SCOPE_FILES,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file",
        side_effect=lambda url: "fake text for " + url,
    ), patch(
        "integrations.mn_sos.tasks.parse_result_file",
        return_value=_SENATE_RESULT_ROWS,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_candidate_table",
        return_value="fake cand text",
    ), patch(
        "integrations.mn_sos.tasks.parse_candidate_table",
        return_value=_CANDIDATE_ROWS,
    ):
        result = sync_mn_races()

    assert result["created"] >= 2  # 1 race + 1 candidate at minimum
    link = ElectionSourceLink.objects.filter(source="mn_sos", source_id="mn_sos_2024_general").first()
    assert link is not None
    election = link.election
    assert election.state == "MN"

    race = Race.objects.get(election=election, office_title="U.S. Senator")
    assert race.source == "mn_sos"

    candidate_names = set(Candidate.objects.filter(race=race).values_list("name", flat=True))
    assert candidate_names == {"Amy Klobuchar"}  # county candidate excluded, write-in row excluded


@pytest.mark.django_db
def test_sync_mn_races_marks_disappeared_candidate_withdrawn():
    with patch(
        "integrations.mn_sos.tasks.probe_in_scope_files",
        return_value=_IN_SCOPE_FILES,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file",
        side_effect=lambda url: "fake text for " + url,
    ), patch(
        "integrations.mn_sos.tasks.parse_result_file",
        return_value=_SENATE_RESULT_ROWS,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_candidate_table",
        return_value="fake cand text",
    ), patch(
        "integrations.mn_sos.tasks.parse_candidate_table",
        return_value=_CANDIDATE_ROWS,
    ):
        sync_mn_races()

    race = Race.objects.get(office_title="U.S. Senator")
    Candidate.objects.create(race=race, name="Someone Who Withdrew", party="DFL")

    with patch(
        "integrations.mn_sos.tasks.probe_in_scope_files",
        return_value=_IN_SCOPE_FILES,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file",
        side_effect=lambda url: "fake text for " + url,
    ), patch(
        "integrations.mn_sos.tasks.parse_result_file",
        return_value=_SENATE_RESULT_ROWS,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_candidate_table",
        return_value="fake cand text",
    ), patch(
        "integrations.mn_sos.tasks.parse_candidate_table",
        return_value=_CANDIDATE_ROWS,
    ):
        sync_mn_races()

    withdrawn = Candidate.objects.get(name="Someone Who Withdrew")
    assert withdrawn.candidate_status == Candidate.CandidateStatus.WITHDRAWN


_STSENATE_RESULT_ROWS = [
    {
        "state": "MN", "county_id": "", "precinct_name": "", "office_id": "0201",
        "office_name": "State Senator District 1", "district": "1",
        "candidate_order_code": "0301", "candidate_name": "Jane Statehouse", "suffix": "",
        "incumbent_code": "", "party": "DFL", "precincts_reporting": "10",
        "total_precincts": "10", "candidate_votes": "5000", "candidate_pct": "60.00",
        "total_office_votes": "8333",
    },
]

_TWO_IN_SCOPE_FILES = [
    {"label": "U.S. Senator Statewide", "url": "https://x/ussenate.txt"},
    {"label": "State Senator by District", "url": "https://x/stsenate.txt"},
]

_CANDIDATE_ROWS_TWO_OFFICES = _CANDIDATE_ROWS + [
    {
        "candidate_id": "02010301", "candidate_name": "Jane Statehouse",
        "office_id": "0201", "office_title": "State Senator District 1",
        "county_id": "88", "order_code": "01", "party": "DFL",
    },
]


def _fake_parse_result_file(text):
    if "ussenate" in text:
        return _SENATE_RESULT_ROWS
    if "stsenate" in text:
        return _STSENATE_RESULT_ROWS
    return []


@pytest.mark.django_db
def test_sync_mn_races_skips_withdrawal_check_on_partial_fetch_failure():
    # Run 1: both result files fetch successfully, seeding a RUNNING candidate
    # for each of two distinct offices (U.S. Senator and State Senator).
    with patch(
        "integrations.mn_sos.tasks.probe_in_scope_files",
        return_value=_TWO_IN_SCOPE_FILES,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file",
        side_effect=lambda url: "fake text for " + url,
    ), patch(
        "integrations.mn_sos.tasks.parse_result_file",
        side_effect=_fake_parse_result_file,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_candidate_table",
        return_value="fake cand text",
    ), patch(
        "integrations.mn_sos.tasks.parse_candidate_table",
        return_value=_CANDIDATE_ROWS_TWO_OFFICES,
    ):
        sync_mn_races()

    state_senate_candidate = Candidate.objects.get(name="Jane Statehouse")
    assert state_senate_candidate.candidate_status == Candidate.CandidateStatus.RUNNING

    # Run 2: the State Senator result file fails to fetch this run, so its
    # office never enters in_scope_office_ids. Without the fix, this would
    # cause the withdrawal pass to wrongly mark Jane Statehouse as WITHDRAWN
    # even though she never actually withdrew — it was just a transient
    # fetch failure on an unrelated file.
    def fetch_file_one_fails(url):
        if "stsenate" in url:
            raise Exception("simulated transient fetch failure")
        return "fake text for " + url

    with patch(
        "integrations.mn_sos.tasks.probe_in_scope_files",
        return_value=_TWO_IN_SCOPE_FILES,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file",
        side_effect=fetch_file_one_fails,
    ), patch(
        "integrations.mn_sos.tasks.parse_result_file",
        side_effect=_fake_parse_result_file,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_candidate_table",
        return_value="fake cand text",
    ), patch(
        "integrations.mn_sos.tasks.parse_candidate_table",
        return_value=_CANDIDATE_ROWS_TWO_OFFICES,
    ):
        result = sync_mn_races()

    state_senate_candidate.refresh_from_db()
    assert state_senate_candidate.candidate_status == Candidate.CandidateStatus.RUNNING
    assert result["withdrawn"] == 0


_ELECTION_WITHOUT_DATE_PATH = {
    "source_id": "mn_sos_2024_general",
    "name": "2024 Minnesota General Election",
    "election_date": datetime.date(2024, 11, 5),
    "election_type": "general",
    "jurisdiction_level": Election.JurisdictionLevel.STATE,
    "state": "MN",
    "status": Election.Status.RESULTS_CERTIFIED,
    "source_metadata": {"mn_ers_election_id": 170},  # no mn_date_path
}


@pytest.mark.django_db
def test_sync_mn_races_records_clear_error_when_date_path_metadata_missing():
    # An election lacking mn_date_path (stale/registry gap/manual edit) must be
    # recorded as a clear error in the SyncLog, not raise a bare KeyError. With
    # one registry election failing, the whole run reports FAILED.
    with patch(
        "integrations.mn_sos.tasks.map_election",
        return_value=dict(_ELECTION_WITHOUT_DATE_PATH),
    ):
        result = sync_mn_races()

    assert result["created"] == 0
    log = SyncLog.objects.filter(source="mn_sos").order_by("-id").first()
    assert log.status == SyncLog.Status.FAILED
    assert "mn_date_path" in (log.last_error or "")


@pytest.mark.django_db
def test_sync_mn_races_iterates_multiple_registered_elections():
    # Two registered elections, each with the same in-scope Senate file/roster,
    # produce a distinct Election + race + candidate; counts aggregate.
    e1 = MnElection(
        election_date=datetime.date(2024, 11, 5), election_type="general",
        name="2024 Minnesota General Election", source_id="mn_sos_2024_general",
        ers_election_id=170,
    )
    e2 = MnElection(
        election_date=datetime.date(2026, 8, 11), election_type="primary",
        name="2026 Minnesota Primary",
    )
    with patch(
        "integrations.mn_sos.tasks.registered_elections", return_value=[e1, e2],
    ), patch(
        "integrations.mn_sos.tasks.probe_in_scope_files", return_value=_IN_SCOPE_FILES,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_file",
        side_effect=lambda url: "fake text for " + url,
    ), patch(
        "integrations.mn_sos.tasks.parse_result_file", return_value=_SENATE_RESULT_ROWS,
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.fetch_candidate_table",
        return_value="fake cand text",
    ), patch(
        "integrations.mn_sos.tasks.parse_candidate_table", return_value=_CANDIDATE_ROWS,
    ):
        result = sync_mn_races()

    assert Election.objects.filter(source_metadata__mn_date_path="20241105").exists()
    assert Election.objects.filter(source_metadata__mn_date_path="20260811").exists()
    # one U.S. Senator race + one Klobuchar candidate per election
    assert result["created"] == 4
    log = SyncLog.objects.filter(source="mn_sos").order_by("-id").first()
    assert log.status == SyncLog.Status.COMPLETED
    assert "elections=2 ok=2" in log.notes


@pytest.mark.django_db
def test_discover_registers_new_election_when_cand_file_exists():
    with patch(
        "integrations.mn_sos.tasks.statutory_statewide_elections",
        return_value=[(datetime.date(2026, 8, 11), "primary", "2026 Minnesota Primary")],
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.file_exists", return_value=True,
    ):
        result = discover_mn_elections()

    assert "mn_sos_20260811" in result["registered"]
    link = ElectionSourceLink.objects.get(source="mn_sos", source_id="mn_sos_20260811")
    assert link.election.source_metadata["mn_date_path"] == "20260811"
    assert link.election.election_type == "primary"


@pytest.mark.django_db
def test_discover_skips_when_cand_file_absent():
    with patch(
        "integrations.mn_sos.tasks.statutory_statewide_elections",
        return_value=[(datetime.date(2028, 8, 8), "primary", "2028 Minnesota Primary")],
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.file_exists", return_value=False,
    ):
        result = discover_mn_elections()

    assert result["registered"] == []
    assert not ElectionSourceLink.objects.filter(source="mn_sos", source_id="mn_sos_20280808").exists()


@pytest.mark.django_db
def test_discover_skips_already_registered_date_without_probing():
    # 2024 general is in the TOML seed (date_path 20241105); discovery must not
    # re-probe or re-register it.
    with patch(
        "integrations.mn_sos.tasks.statutory_statewide_elections",
        return_value=[(datetime.date(2024, 11, 5), "general", "2024 Minnesota General Election")],
    ), patch(
        "integrations.mn_sos.tasks.MnSosClient.file_exists", return_value=True,
    ) as file_exists:
        result = discover_mn_elections()

    assert result["registered"] == []
    file_exists.assert_not_called()

from unittest.mock import patch

import pytest

from elections.models import Candidate, ElectionSourceLink, Race
from integrations.mn_sos.tasks import sync_mn_races

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

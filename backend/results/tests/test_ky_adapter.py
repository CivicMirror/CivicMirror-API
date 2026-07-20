"""
Unit tests for the Kentucky SBE XML results adapter.
HTTP calls are mocked; no network access required.
"""
from __future__ import annotations

import textwrap
from datetime import date
from unittest.mock import patch

import pytest

from results.models import OfficialResult

_ELECTIONS_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <Elections>
      <Election ElectionId="550" ElectionName="2026 Primary Election"
                ElectionType="Primary" ElectionDate="05/19/2026" />
      <Election ElectionId="551" ElectionName="2026 General Election"
                ElectionType="General" ElectionDate="11/03/2026" />
    </Elections>
""").encode()

_CONTESTS_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <Contests>
      <Contest ElectionId="550" ContestId="10"
               ContestName="United States Senator"
               ContestScopeUnitId="2" IsPartisan="true"
               IsUncontested="false" SelectableOption="1"
               PoliticalPartyId="1" />
      <Contest ElectionId="550" ContestId="11"
               ContestName="Constitutional Amendment 1"
               ContestScopeUnitId="2" IsPartisan="false"
               SelectableOption="1" PoliticalPartyId="0" />
      <Contest ElectionId="551" ContestId="99"
               ContestName="Other Election Contest"
               ContestScopeUnitId="2" IsPartisan="true"
               SelectableOption="1" PoliticalPartyId="1" />
    </Contests>
""").encode()

_CANDIDATES_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <Candidates>
      <Candidate ElectionId="550" ContestId="10" CandidateId="101"
                 BallotName="Jane Smith" PoliticalPartyId="1"
                 IsIncumbent="false" IsWriteIn="false" IsWithdrawn="false" />
      <Candidate ElectionId="550" ContestId="10" CandidateId="102"
                 BallotName="Write-in" PoliticalPartyId="0"
                 IsIncumbent="false" IsWriteIn="true" IsWithdrawn="false" />
      <Candidate ElectionId="550" ContestId="11" CandidateId="201"
                 BallotName="Yes" PoliticalPartyId="0"
                 IsIncumbent="false" IsWriteIn="false" IsWithdrawn="false" />
      <Candidate ElectionId="550" ContestId="11" CandidateId="202"
                 BallotName="No" PoliticalPartyId="0"
                 IsIncumbent="false" IsWriteIn="false" IsWithdrawn="false" />
      <Candidate ElectionId="551" ContestId="99" CandidateId="999"
                 BallotName="Wrong Election" PoliticalPartyId="1"
                 IsIncumbent="false" IsWriteIn="false" IsWithdrawn="false" />
    </Candidates>
""").encode()

_CURRENT_RESULTS_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <CurrentResults>
      <CandidateDataList>
        <CandidateData gpu_id="2" contest_id="10" candidate_id="101"
                       total_votes="1,234" election_day_votes="1000" />
        <CandidateData gpu_id="2" contest_id="10" candidate_id="102"
                       total_votes="7" election_day_votes="5" />
        <CandidateData gpu_id="2" contest_id="11" candidate_id="201"
                       total_votes="800" election_day_votes="600" />
        <CandidateData gpu_id="2" contest_id="11" candidate_id="202"
                       total_votes="700" election_day_votes="650" />
        <CandidateData gpu_id="2" contest_id="99" candidate_id="999"
                       total_votes="9999" election_day_votes="9999" />
      </CandidateDataList>
      <ReportDataList>
        <ReportData gpu_id="2" status="FinalReporting"
                    precinct_participating="3189" precinct_reporting="3189"
                    ballots_cast="864365" registered_voters="3365369" />
      </ReportDataList>
    </CurrentResults>
""").encode()


def test_parse_ky_xml_results_joins_contests_candidates_and_reporting_status():
    from results.adapters.ky import parse_ky_xml_results

    rows = parse_ky_xml_results(
        election_id="550",
        contests_xml=_CONTESTS_XML,
        candidates_xml=_CANDIDATES_XML,
        current_results_xml=_CURRENT_RESULTS_XML,
    )

    smith = next(row for row in rows if row.candidate_name == "Jane Smith")

    assert smith.office_title == "United States Senator"
    assert smith.vote_count == 1234
    assert smith.result_type == OfficialResult.ResultType.UNOFFICIAL
    assert smith.is_write_in_aggregate is False
    assert smith.jurisdiction_fragment == "2"
    assert smith.raw["contest_code"] == "10"
    assert smith.raw["candidate_id"] == "101"
    assert smith.raw["gpu_id"] == "2"
    assert smith.raw["reporting_status"] == "FinalReporting"
    assert smith.raw["absentee_votes"] == 234


def test_parse_ky_xml_results_marks_write_in_aggregate():
    from results.adapters.ky import parse_ky_xml_results

    rows = parse_ky_xml_results("550", _CONTESTS_XML, _CANDIDATES_XML, _CURRENT_RESULTS_XML)

    write_in = next(row for row in rows if row.is_write_in_aggregate)
    assert write_in.office_title == "United States Senator"
    assert write_in.candidate_name is None
    assert write_in.vote_count == 7


def test_parse_ky_xml_results_treats_measure_choices_as_options():
    from results.adapters.ky import parse_ky_xml_results

    rows = parse_ky_xml_results("550", _CONTESTS_XML, _CANDIDATES_XML, _CURRENT_RESULTS_XML)

    yes = next(row for row in rows if row.option_label == "Yes")
    assert yes.office_title == "Constitutional Amendment 1"
    assert yes.candidate_name is None
    assert yes.vote_count == 800


def test_parse_ky_xml_results_keeps_nonpartisan_candidate_contests_as_candidates():
    from results.adapters.ky import parse_ky_xml_results

    contests_xml = textwrap.dedent("""\
        <Contests>
          <Contest ElectionId="550" ContestId="12"
                   ContestName="District Judge 1st District"
                   IsPartisan="false" PoliticalPartyId="0" />
        </Contests>
    """).encode()
    candidates_xml = textwrap.dedent("""\
        <Candidates>
          <Candidate ElectionId="550" ContestId="12" CandidateId="301"
                     BallotName="Alex Judge" PoliticalPartyId="0"
                     IsWriteIn="false" />
        </Candidates>
    """).encode()
    current_xml = textwrap.dedent("""\
        <CurrentResults>
          <CandidateDataList>
            <CandidateData gpu_id="2" contest_id="12" candidate_id="301"
                           total_votes="12" election_day_votes="10" />
          </CandidateDataList>
        </CurrentResults>
    """).encode()

    rows = parse_ky_xml_results("550", contests_xml, candidates_xml, current_xml)

    assert rows[0].candidate_name == "Alex Judge"
    assert rows[0].option_label is None


def test_parse_ky_xml_results_filters_other_elections():
    from results.adapters.ky import parse_ky_xml_results

    rows = parse_ky_xml_results("550", _CONTESTS_XML, _CANDIDATES_XML, _CURRENT_RESULTS_XML)

    assert all(row.raw["contest_code"] != "99" for row in rows)


def test_parse_ky_xml_results_accepts_gup_id_typo_variant_for_gpu_id():
    from results.adapters.ky import parse_ky_xml_results

    contests_xml = textwrap.dedent("""\
        <Contests>
          <Contest ElectionId="550" ContestId="20"
                   ContestName="State Auditor"
                   IsPartisan="true" PoliticalPartyId="1" />
        </Contests>
    """).encode()
    candidates_xml = textwrap.dedent("""\
        <Candidates>
          <Candidate ElectionId="550" ContestId="20" CandidateId="401"
                     BallotName="Sam Auditor" PoliticalPartyId="1"
                     IsWriteIn="false" />
        </Candidates>
    """).encode()
    current_xml = textwrap.dedent("""\
        <CurrentResults>
          <CandidateDataList>
            <CandidateData Gup_id="7" contest_id="20" candidate_id="401"
                           total_votes="50" election_day_votes="40" />
          </CandidateDataList>
          <ReportDataList>
            <ReportData Gup_id="7" status="PartialReporting"
                        precinct_participating="10" precinct_reporting="5"
                        ballots_cast="1000" registered_voters="2000" />
          </ReportDataList>
        </CurrentResults>
    """).encode()

    rows = parse_ky_xml_results("550", contests_xml, candidates_xml, current_xml)

    assert rows[0].jurisdiction_fragment == "7"
    assert rows[0].raw["reporting_status"] == "PartialReporting"
    assert rows[0].raw["precinct_reporting"] == 5


def test_select_ky_election_id_prefers_source_metadata():
    from results.adapters.ky import select_ky_election_id

    election = type("Election", (), {
        "election_date": date(2026, 5, 19),
        "election_type": "primary",
        "source_metadata": {"ky_election_id": "550"},
    })()

    assert select_ky_election_id(election, _ELECTIONS_XML) == "550"


def test_select_ky_election_id_can_match_date_and_type():
    from results.adapters.ky import select_ky_election_id

    election = type("Election", (), {
        "election_date": date(2026, 5, 19),
        "election_type": "primary",
        "source_metadata": {},
    })()

    assert select_ky_election_id(election, _ELECTIONS_XML) == "550"


def test_select_ky_election_id_prefers_exact_type_over_substring_match():
    from results.adapters.ky import select_ky_election_id

    elections_xml = textwrap.dedent("""\
        <?xml version="1.0" encoding="utf-8"?>
        <Elections>
          <Election ElectionId="600" ElectionName="2026 Primary Runoff"
                    ElectionType="Primary Runoff" ElectionDate="05/19/2026" />
          <Election ElectionId="601" ElectionName="2026 Primary Election"
                    ElectionType="Primary" ElectionDate="05/19/2026" />
        </Elections>
    """).encode()

    election = type("Election", (), {
        "election_date": date(2026, 5, 19),
        "election_type": "primary",
        "source_metadata": {},
    })()

    # "primary" is a substring of "primary runoff" too, so a same-day Primary
    # and Primary Runoff must not be conflated: the exact type match (601)
    # should win even though the runoff entry (600) appears first in the XML.
    assert select_ky_election_id(election, elections_xml) == "601"


@pytest.mark.django_db
def test_ky_adapter_fetches_metadata_and_current_results():
    from elections.models import Election
    from results.adapters.ky import KentuckyAdapter

    election = Election.objects.create(
        source_id="ky-test-primary",
        name="2026 Kentucky Primary Election",
        state="KY",
        election_type="primary",
        election_date=date(2026, 5, 19),
        status="results_pending",
        jurisdiction_level="state",
        source_metadata={"ky_election_id": "550"},
    )

    with patch("results.adapters.ky.cache") as mock_cache, \
         patch("results.adapters.ky.KentuckyXmlClient") as MockClient:
        mock_cache.get.return_value = None
        MockClient.return_value.fetch_elections.return_value = _ELECTIONS_XML
        MockClient.return_value.fetch_contests.return_value = _CONTESTS_XML
        MockClient.return_value.fetch_candidates.return_value = _CANDIDATES_XML
        MockClient.return_value.fetch_current_results.return_value = _CURRENT_RESULTS_XML

        result = KentuckyAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    assert result.source_url.endswith("/CurrentResultsExcludeLocal")
    assert len(result.rows) == 4
    assert result.source_version


@pytest.mark.django_db
def test_ky_adapter_returns_unchanged_when_source_hash_matches():
    from elections.models import Election
    from results.adapters.ky import KentuckyAdapter, source_version_for

    election = Election.objects.create(
        source_id="ky-test-primary-unchanged",
        name="2026 Kentucky Primary Election",
        state="KY",
        election_type="primary",
        election_date=date(2026, 5, 19),
        status="results_pending",
        jurisdiction_level="state",
        source_metadata={"ky_election_id": "550"},
    )
    version = source_version_for(_CURRENT_RESULTS_XML)

    with patch("results.adapters.ky.cache") as mock_cache, \
         patch("results.adapters.ky.KentuckyXmlClient") as MockClient:
        mock_cache.get.return_value = version
        MockClient.return_value.fetch_elections.return_value = _ELECTIONS_XML
        MockClient.return_value.fetch_current_results.return_value = _CURRENT_RESULTS_XML

        result = KentuckyAdapter().fetch_results(election.election_date, election.pk)

    assert result.unchanged is True
    assert result.rows == []
    assert result.source_version == version
    MockClient.return_value.fetch_contests.assert_not_called()
    MockClient.return_value.fetch_candidates.assert_not_called()


@pytest.mark.django_db
def test_ky_adapter_reports_policy_block_as_unavailable_feed():
    from elections.models import Election
    from results.adapters.ky import KentuckyAdapter, KentuckyPolicyBlockError

    election = Election.objects.create(
        source_id="ky-test-primary-policy-block",
        name="2026 Kentucky Primary Election",
        state="KY",
        election_type="primary",
        election_date=date(2026, 5, 19),
        status="results_pending",
        jurisdiction_level="state",
    )

    with patch("results.adapters.ky.KentuckyXmlClient") as MockClient:
        MockClient.return_value.fetch_elections.side_effect = KentuckyPolicyBlockError("Acceptable Use Policy")

        result = KentuckyAdapter().fetch_results(election.election_date, election.pk)

    assert result.rows == []
    assert result.mapping_confidence == "none"
    assert "policy" in result.notes.lower()


def test_ky_adapter_is_registered():
    from results.adapters import list_supported_states

    assert "KY" in list_supported_states()

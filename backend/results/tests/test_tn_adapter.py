from unittest.mock import MagicMock, patch

import pytest

from results.adapters.registry import get_adapter
from results.adapters.tn import TennesseeAdapter


def test_tn_adapter_registered():
    assert get_adapter("TN") is TennesseeAdapter


def test_fetch_results_requires_indexed_result_url():
    adapter = TennesseeAdapter()
    election = MagicMock()
    election.source_metadata = {}

    with patch("elections.models.Election.objects.get", return_value=election):
        result = adapter.fetch_results(None, election_id=1)

    assert result.mapping_confidence == "none"
    assert "tn_results_url" in result.notes or "tn_result_links" in result.notes


def test_fetch_results_parses_precinct_xlsx_fixture():
    adapter = TennesseeAdapter()
    election = MagicMock()
    election.pk = 1
    election.source_metadata = {
        "tn_results_url": "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20251202AllbyPrecinct.xlsx"
    }

    fixture = open("integrations/tn_sos/tests/fixtures/results_20251202_precinct_sample.xlsx", "rb").read()

    with patch("elections.models.Election.objects.get", return_value=election), \
         patch("results.adapters.tn.TnSosClient") as client_cls, \
         patch("results.adapters.tn.cache") as cache:
        cache.get.return_value = None
        client_cls.return_value.download_file.return_value = (fixture, election.source_metadata["tn_results_url"])
        result = adapter.fetch_results(None, election_id=1)

    assert result.mapping_confidence == "full"
    # One statewide total ('' fragment) plus one county row per candidate.
    assert len(result.rows) == 4
    totals = [r for r in result.rows if r.jurisdiction_fragment == ""]
    assert [(r.office_title, r.candidate_name, r.vote_count) for r in totals] == [
        ("U.S. House District 7", "Jane Candidate", 123),
        ("U.S. House District 7", "Alex Example", 98),
    ]
    assert {r.jurisdiction_fragment for r in result.rows} == {"", "Davidson"}


def test_fetch_results_unchanged_when_checksum_cached():
    adapter = TennesseeAdapter()
    election = MagicMock()
    election.pk = 1
    election.source_metadata = {
        "tn_results_url": "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20251202AllbyPrecinct.xlsx"
    }

    fixture = open("integrations/tn_sos/tests/fixtures/results_20251202_precinct_sample.xlsx", "rb").read()

    from integrations.tn_sos.parsers import document_checksum

    with patch("elections.models.Election.objects.get", return_value=election), \
         patch("results.adapters.tn.TnSosClient") as client_cls, \
         patch("results.adapters.tn.cache") as cache:
        cache.get.return_value = document_checksum(fixture)
        client_cls.return_value.download_file.return_value = (fixture, election.source_metadata["tn_results_url"])
        result = adapter.fetch_results(None, election_id=1)

    assert result.unchanged is True
    assert result.rows == []


def test_fetch_results_partial_for_non_xlsx_document():
    adapter = TennesseeAdapter()
    election = MagicMock()
    election.pk = 1
    election.source_metadata = {
        "tn_result_links": [
            {"url": "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20251202results.pdf", "file_type": "pdf"}
        ]
    }

    with patch("elections.models.Election.objects.get", return_value=election):
        result = adapter.fetch_results(None, election_id=1)

    assert result.mapping_confidence == "partial"
    assert result.rows == []


def test_fetch_results_aggregates_sofficel_export_by_county_and_statewide():
    adapter = TennesseeAdapter()
    election = MagicMock()
    election.pk = 1924
    url = "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20260806AllbyPrecinct.xlsx"
    election.source_metadata = {"tn_result_links": [{"url": url, "file_type": "xlsx"}]}
    fixture = open("integrations/tn_sos/tests/fixtures/results_20260806_sofficel_sample.xlsx", "rb").read()

    with patch("elections.models.Election.objects.get", return_value=election), \
         patch("results.adapters.tn.TnSosClient") as client_cls, \
         patch("results.adapters.tn.cache") as cache:
        cache.get.return_value = None
        client_cls.return_value.download_file.return_value = (fixture, url)
        result = adapter.fetch_results(None, election_id=1924)

    assert result.mapping_confidence == "full"
    rows = {(r.office_title, r.candidate_name, r.jurisdiction_fragment): r for r in result.rows}
    # Split-precinct ballot styles are summed within the county: 296 + 4.
    assert rows[("Governor", "Marsha Blackburn", "Anderson")].vote_count == 300
    # Same precinct name in another county stays separate.
    assert rows[("Governor", "Marsha Blackburn", "Union")].vote_count == 50
    # Statewide total across counties.
    assert rows[("Governor", "Marsha Blackburn", "")].vote_count == 350
    assert rows[("Governor", "Jerri Green", "")].vote_count == 73
    assert rows[("Governor", "Jerri Green", "")].raw["contest_type"] == "Democratic Primary"
    assert rows[("Governor", "Marsha Blackburn", "")].raw["party"] == "Republican"


def _rec(name, votes, county="Anderson", office="Governor", party="Republican", contest="Republican Primary"):
    from integrations.tn_sos.parsers import TnResultRecord
    return TnResultRecord(
        county=county, precinct="Andersonville", office_title=office, candidate_name=name,
        party=party, vote_count=votes, source_url="https://example.test/x.xlsx", contest_type=contest,
    )


def test_aggregate_drops_no_candidate_placeholder_and_combines_write_ins():
    from results.adapters.tn import WRITE_IN_LABEL, _aggregate_rows

    rows = _aggregate_rows([
        _rec("Marsha Blackburn", 300),
        _rec("Write-In - David Fey", 3),
        _rec("Write-In - Lore Bergman", 2),
        _rec("Write-In - David Fey", 1, county="Union"),
        _rec("No Candidate Qualified", 0, office="State Executive Committeeman District 5"),
    ], "https://example.test/x.xlsx")

    names = {r.candidate_name for r in rows}
    assert "No Candidate Qualified" not in names
    assert not any(n.startswith("Write-In - ") for n in names)

    by_key = {(r.candidate_name, r.jurisdiction_fragment): r for r in rows}
    statewide = by_key[(WRITE_IN_LABEL, "")]
    assert statewide.is_write_in_aggregate is True
    assert statewide.vote_count == 6
    assert statewide.raw["write_in_names"] == ["Write-In - David Fey", "Write-In - Lore Bergman"]
    assert statewide.raw["party"] == ""
    assert by_key[(WRITE_IN_LABEL, "Anderson")].vote_count == 5
    assert by_key[(WRITE_IN_LABEL, "Union")].vote_count == 1
    assert by_key[("Marsha Blackburn", "")].is_write_in_aggregate is False



@pytest.mark.django_db
def test_tn_race_with_write_ins_and_placeholders_is_certified():
    """Placeholders and named write-ins must no longer leave a race stuck in partial_results."""
    from elections.models import Candidate, Election, Race
    from results.adapters.base import AdapterResult
    from results.adapters.tn import _aggregate_rows
    from results.models import OfficialResult
    from results.tasks import _process_race_results

    election = Election.objects.create(
        source_id="tn-test-2026-08-06", name="TN Primary", election_date="2026-08-06",
        jurisdiction_level=Election.JurisdictionLevel.STATE, state="TN", status=Election.Status.RESULTS_PENDING,
    )
    race = Race.objects.create(
        election=election, race_type=Race.RaceType.CANDIDATE, office_title="Governor",
        jurisdiction="Tennessee", geography_scope="statewide", source=Race.Source.CIVIC_API,
        canonical_key="tn:test:governor",
    )
    Candidate.objects.create(race=race, name="Marsha Blackburn")
    rows = _aggregate_rows([
        _rec("Marsha Blackburn", 300),
        _rec("Write-In - David Fey", 3),
        _rec("No Candidate Qualified", 0),
    ], "https://example.test/x.xlsx")

    _process_race_results(race, AdapterResult(rows=rows, source_url="https://example.test/x.xlsx",
                                              mapping_confidence="full"), "TN")

    race.refresh_from_db()
    assert race.certification_status == Race.CertificationStatus.RESULTS_CERTIFIED
    write_in = OfficialResult.objects.get(race=race, is_write_in_aggregate=True, jurisdiction_fragment="")
    assert write_in.candidate is None and write_in.vote_count == 3
    assert OfficialResult.objects.get(race=race, candidate__name="Marsha Blackburn", jurisdiction_fragment="").vote_count == 300

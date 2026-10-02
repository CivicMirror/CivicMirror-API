from unittest.mock import MagicMock, patch

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

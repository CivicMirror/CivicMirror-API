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
    assert len(result.rows) == 2
    assert result.rows[0].office_title == "U.S. House District 7"
    assert result.rows[0].candidate_name == "Jane Candidate"
    assert result.rows[0].vote_count == 123


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

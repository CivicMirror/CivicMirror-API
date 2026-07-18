from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from results.adapters.al import AlabamaAdapter
from results.adapters.registry import get_adapter

FIXTURES = Path(__file__).parents[2] / "integrations" / "al_sos" / "tests" / "fixtures"


@pytest.mark.django_db
def test_alabama_adapter_fetches_by_ecode_metadata():
    from elections.models import Election

    election = Election.objects.create(
        source_id="al_2026_runoff",
        name="2026 Alabama Primary Runoff",
        state="AL",
        election_type="primary",
        election_date=date(2026, 6, 16),
        status="RESULTS_PENDING",
        jurisdiction_level="STATE",
        source_metadata={"al_ecode": "1001295"},
    )
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()

    with patch("results.adapters.al.cache") as mock_cache, \
         patch("results.adapters.al.AlSosClient") as MockClient:
        mock_cache.get.return_value = None
        MockClient.return_value.fetch_enr_export.return_value = content

        result = AlabamaAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    assert result.source_url.endswith("ecode=1001295")
    assert result.source_version.startswith("1001295:")
    assert len(result.rows) > 0
    MockClient.return_value.fetch_enr_export.assert_called_once_with("1001295")


@pytest.mark.django_db
def test_alabama_adapter_returns_unchanged_when_source_version_matches():
    from elections.models import Election

    election = Election.objects.create(
        source_id="al_2026_runoff_cached",
        name="2026 Alabama Primary Runoff",
        state="AL",
        election_type="primary",
        election_date=date(2026, 6, 16),
        status="RESULTS_PENDING",
        jurisdiction_level="STATE",
        source_metadata={"al_ecode": "1001295"},
    )
    content = (FIXTURES / "al_sos_enr_export.xlsx").read_bytes()

    with patch("results.adapters.al.cache") as mock_cache, \
         patch("results.adapters.al.AlSosClient") as MockClient:
        MockClient.return_value.fetch_enr_export.return_value = content
        first = AlabamaAdapter().fetch_results(election.election_date, election.pk)
        mock_cache.get.return_value = first.source_version

        second = AlabamaAdapter().fetch_results(election.election_date, election.pk)

    assert second.unchanged is True
    assert second.rows == []
    assert second.source_version == first.source_version


@pytest.mark.django_db
def test_alabama_adapter_requires_ecode_or_results_url():
    from elections.models import Election

    election = Election.objects.create(
        source_id="al_missing_metadata",
        name="2026 Alabama Primary Runoff",
        state="AL",
        election_type="primary",
        election_date=date(2026, 6, 16),
        status="RESULTS_PENDING",
        jurisdiction_level="STATE",
        source_metadata={},
    )

    result = AlabamaAdapter().fetch_results(election.election_date, election.pk)

    assert result.rows == []
    assert result.mapping_confidence == "none"
    assert "al_ecode" in result.notes


def test_alabama_adapter_registered_at_startup():
    assert get_adapter("AL") is AlabamaAdapter


def test_results_config_imports_alabama_adapter_at_startup():
    import results
    from results.apps import ResultsConfig

    with patch("results.apps.import_module") as mock_import_module:
        ResultsConfig("results", results).ready()

    mock_import_module.assert_any_call("results.adapters.al")

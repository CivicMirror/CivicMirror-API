from unittest.mock import patch

import pytest
from django.core.cache import cache

from elections.models import Election
from results.adapters.mi import MichiganAdapter


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_mi_adapter_registered():
    import results.adapters.mi  # noqa: F401
    from results.adapters.registry import get_adapter, list_supported_states

    assert "MI" in list_supported_states()
    assert get_adapter("MI") is MichiganAdapter


@pytest.mark.django_db
def test_fetch_results_requires_mvic_election_id_metadata():
    election = Election.objects.create(
        name="MI Test",
        election_date="2026-05-05",
        election_type="special",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MI",
        source_id="mi_test",
    )

    result = MichiganAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "none"
    assert "mi_mvic_election_id" in result.notes


@pytest.mark.django_db
@patch("results.adapters.mi.MiSosClient")
def test_fetch_results_uses_bulk_file_first(client_cls):
    election = Election.objects.create(
        name="MI Test",
        election_date="2026-05-05",
        election_type="special",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MI",
        source_id="mi_test",
        source_metadata={"mi_mvic_election_id": 705},
    )
    client_cls.return_value.fetch_result_file.return_value = (
        "contest\tcandidate\tparty\tvotes\tpct\tcounty\n"
        "35TH DISTRICT STATE SENATOR\tGREENE, CHEDRICK\tDEMOCRATIC\t36583\t58.88\tBAY\n"
    )

    result = MichiganAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    assert result.rows[0].candidate_name == "GREENE, CHEDRICK"
    assert result.rows[0].vote_count == 36583
    assert result.rows[0].vote_pct == 58.88
    assert result.rows[0].jurisdiction_fragment == "BAY"
    assert result.rows[0].office_title == "State Senate - District 35"
    client_cls.return_value.fetch_county_vote_records.assert_not_called()


@pytest.mark.django_db
@patch("results.adapters.mi.MiSosClient")
def test_fetch_results_falls_back_to_html_when_bulk_fetch_fails(client_cls):
    from integrations.mi_sos.exceptions import MiSosRetryableError

    election = Election.objects.create(
        name="MI Test",
        election_date="2026-05-05",
        election_type="special",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MI",
        source_id="mi_test",
        source_metadata={"mi_mvic_election_id": 705},
    )
    client = client_cls.return_value
    client.fetch_result_file.side_effect = MiSosRetryableError("cf blocked")
    client.fetch_county_vote_records.return_value = """
    35TH DISTRICT STATE SENATOR PARTIAL TERM ENDING 1/1/2027 (1) POSITION
    DEMOCRATIC
    GREENE, CHEDRICK  36,583  58.88%
    """

    result = MichiganAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "partial"
    assert result.rows[0].candidate_name == "GREENE, CHEDRICK"
    assert result.rows[0].vote_count == 36583


@pytest.mark.django_db
@patch("results.adapters.mi.MiSosClient")
def test_fetch_results_reports_unchanged_when_checksum_matches_cache(client_cls):
    election = Election.objects.create(
        name="MI Test",
        election_date="2026-05-05",
        election_type="special",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MI",
        source_id="mi_test",
        source_metadata={"mi_mvic_election_id": 705},
    )
    adapter = MichiganAdapter()
    client_cls.return_value.fetch_result_file.return_value = (
        "contest\tcandidate\tparty\tvotes\tpct\tcounty\n"
        "35TH DISTRICT STATE SENATOR\tGREENE, CHEDRICK\tDEMOCRATIC\t36583\t58.88\tBAY\n"
    )

    first = adapter.fetch_results(election.election_date, election.pk)
    cache.set(adapter.version_cache_key(election.pk), first.source_version, 86400)
    second = adapter.fetch_results(election.election_date, election.pk)

    assert second.unchanged is True
    assert second.rows == []

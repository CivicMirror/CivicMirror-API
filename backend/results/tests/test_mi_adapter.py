from pathlib import Path
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
        source_metadata={"mi_mvic_election_id": 706},
    )
    # Real MVIC bulk output. The inline text this test used to pass had invented
    # column names (contest/candidate/votes), so it hid the parser returning nothing
    # on the actual file, whose columns are OfficeDescription/CandidateLastName/
    # CandidateVotes behind a preamble line.
    fixture = (
        Path(__file__).parents[2]
        / "integrations" / "mi_sos" / "tests" / "fixtures" / "mvic_result_file_706.txt"
    ).read_text(encoding="utf-8")
    client_cls.return_value.fetch_result_file.return_value = fixture

    result = MichiganAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    governor = [r for r in result.rows if r.office_title == "Governor"]
    assert governor

    totals = [r for r in governor if r.jurisdiction_fragment == ""]
    benson_total = next(r for r in totals if r.candidate_name == "Benson, Jocelyn")
    counties = [
        r for r in governor
        if r.jurisdiction_fragment and r.candidate_name == "Benson, Jocelyn"
    ]
    assert benson_total.vote_count == sum(r.vote_count for r in counties)
    assert {r.jurisdiction_fragment for r in counties} == {"ALCONA", "WAYNE", "OAKLAND"}

    # The file declares "RESULTS: OFFICIAL" in its trailer, so these are official.
    assert {r.result_type for r in result.rows} == {"official"}
    client_cls.return_value.fetch_county_vote_records.assert_not_called()


@pytest.mark.django_db
@patch("results.adapters.mi.MiSosClient")
def test_election_night_returns_are_not_reported_as_official(client_cls):
    """MVIC's trailer says UNOFFICIAL until the canvass completes; trust it."""
    election = Election.objects.create(
        name="MI Test",
        election_date="2026-05-05",
        election_type="special",
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MI",
        source_id="mi_test_unofficial",
        source_metadata={"mi_mvic_election_id": 706},
    )
    fixture = (
        Path(__file__).parents[2]
        / "integrations" / "mi_sos" / "tests" / "fixtures" / "mvic_result_file_706.txt"
    ).read_text(encoding="utf-8")
    client_cls.return_value.fetch_result_file.return_value = fixture.replace(
        "RESULTS: OFFICIAL", "RESULTS: UNOFFICIAL"
    )

    result = MichiganAdapter().fetch_results(election.election_date, election.pk)

    assert result.rows
    assert {r.result_type for r in result.rows} == {"unofficial"}


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
        source_metadata={"mi_mvic_election_id": 706},
    )
    client = client_cls.return_value
    client.fetch_result_file.side_effect = MiSosRetryableError("cf blocked")
    # Real MVIC markup, captured from electionId=706. The inline text this test used
    # to pass was in a shape MVIC does not produce, so it hid the fallback parser
    # returning nothing on live input.
    fixture = (
        Path(__file__).parents[2]
        / "integrations" / "mi_sos" / "tests" / "fixtures" / "mvic_county_records_706.html"
    ).read_text(encoding="utf-8")
    client.fetch_county_vote_records.return_value = fixture

    result = MichiganAdapter().fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "partial"
    by_name = {row.candidate_name: row for row in result.rows}
    assert by_name["Benson, Jocelyn"].vote_count == 1251160
    assert by_name["Benson, Jocelyn"].vote_pct == 83.22
    assert by_name["Benson, Jocelyn"].office_title == "Governor"
    assert by_name["Benson, Jocelyn"].jurisdiction_fragment == ""
    # Write-ins are aggregated, not treated as a candidate.
    assert by_name["WRITE-IN"].is_write_in_aggregate is True


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

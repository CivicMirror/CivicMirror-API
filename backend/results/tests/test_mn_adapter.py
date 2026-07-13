import os
from unittest.mock import patch

import pytest
from django.core.cache import cache

from elections.models import Election
from results.adapters.mn import MinnesotaAdapter

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_fetch_results_returns_none_confidence_when_metadata_missing():
    election = Election.objects.create(
        name="2024 Minnesota General Election", election_date="2024-11-05",
        election_type="general", jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MN", source_id="mn_sos_2024_general",
    )
    adapter = MinnesotaAdapter()
    result = adapter.fetch_results(election.election_date, election.pk)
    assert result.mapping_confidence == "none"
    assert result.rows == []


@pytest.mark.django_db
def test_fetch_results_parses_in_scope_files_only():
    election = Election.objects.create(
        name="2024 Minnesota General Election", election_date="2024-11-05",
        election_type="general", jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MN", source_id="mn_sos_2024_general",
        source_metadata={"mn_ers_election_id": 170, "mn_date_path": "20241105"},
    )
    adapter = MinnesotaAdapter()

    index_html = _load_fixture("mn_file_index.html")
    ussenate_text = _load_fixture("mn_ussenate.txt")

    def fake_fetch_file(url):
        if url.endswith("ussenate.txt"):
            return ussenate_text
        return ""

    with patch(
        "results.adapters.mn.MnSosClient.fetch_file_index", return_value=index_html,
    ), patch(
        "results.adapters.mn.MnSosClient.fetch_file", side_effect=fake_fetch_file,
    ):
        result = adapter.fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    klobuchar = next(r for r in result.rows if r.candidate_name == "Amy Klobuchar")
    assert klobuchar.vote_count == 1792441
    assert klobuchar.office_title == "U.S. Senator"
    write_in = next(r for r in result.rows if r.is_write_in_aggregate)
    assert write_in.candidate_name == "WRITE-IN"
    assert result.source_version  # checksum computed


@pytest.mark.django_db
def test_fetch_results_reports_unchanged_when_checksum_matches_cache():
    election = Election.objects.create(
        name="2024 Minnesota General Election", election_date="2024-11-05",
        election_type="general", jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MN", source_id="mn_sos_2024_general",
        source_metadata={"mn_ers_election_id": 170, "mn_date_path": "20241105"},
    )
    adapter = MinnesotaAdapter()
    index_html = _load_fixture("mn_file_index.html")
    ussenate_text = _load_fixture("mn_ussenate.txt")

    def fake_fetch_file(url):
        return ussenate_text if url.endswith("ussenate.txt") else ""

    with patch(
        "results.adapters.mn.MnSosClient.fetch_file_index", return_value=index_html,
    ), patch(
        "results.adapters.mn.MnSosClient.fetch_file", side_effect=fake_fetch_file,
    ):
        first = adapter.fetch_results(election.election_date, election.pk)
        cache.set(adapter.version_cache_key(election.pk), first.source_version, 86400)
        second = adapter.fetch_results(election.election_date, election.pk)

    assert second.unchanged is True
    assert second.rows == []


@pytest.mark.django_db
def test_fetch_results_skips_malformed_row_but_keeps_valid_rows():
    election = Election.objects.create(
        name="2024 Minnesota General Election", election_date="2024-11-05",
        election_type="general", jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MN", source_id="mn_sos_2024_general",
        source_metadata={"mn_ers_election_id": 170, "mn_date_path": "20241105"},
    )
    adapter = MinnesotaAdapter()
    index_html = _load_fixture("mn_file_index.html")

    # One row with a non-numeric candidate_votes field (malformed) and one
    # otherwise-valid row, in the same file.
    malformed_text = (
        "MN;;;0102;U.S. Senator;;0202;Amy Klobuchar;;;DFL;4103;4103;NOT_A_NUMBER;56.20;3189323\r\n"
        "MN;;;0102;U.S. Senator;;0104;Royce White;;;R;4103;4103;1291712;40.50;3189323\r\n"
    )

    def fake_fetch_file(url):
        return malformed_text if url.endswith("ussenate.txt") else ""

    with patch(
        "results.adapters.mn.MnSosClient.fetch_file_index", return_value=index_html,
    ), patch(
        "results.adapters.mn.MnSosClient.fetch_file", side_effect=fake_fetch_file,
    ):
        result = adapter.fetch_results(election.election_date, election.pk)

    assert result.mapping_confidence == "full"
    names = {r.candidate_name for r in result.rows}
    assert names == {"Royce White"}
    royce = next(r for r in result.rows if r.candidate_name == "Royce White")
    assert royce.vote_count == 1291712

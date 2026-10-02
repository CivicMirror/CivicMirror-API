from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, Race
from integrations.tn_sos.tasks import sync_tn_candidates, sync_tn_elections, sync_tn_result_index

FIXTURES = Path(__file__).parent / "fixtures"


def _make_tn_election(election_date=date(2026, 8, 6), **overrides):
    fields = {
        "name": "Thursday, August 6, 2026 - Primary and General Election",
        "election_date": election_date,
        "election_type": Election.ElectionType.PRIMARY,
        "jurisdiction_level": Election.JurisdictionLevel.STATE,
        "state": "TN",
        "status": Election.Status.UPCOMING,
        "source_id": f"tn_sos:{election_date.isoformat()}:statewide",
    }
    fields.update(overrides)
    return Election.objects.create(**fields)


@pytest.mark.django_db
def test_sync_tn_elections_ingests_statewide_calendar_elections():
    calendar_html = (FIXTURES / "calendar_2026.html").read_text()

    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_calendar_html",
        return_value=calendar_html,
    ), patch("integrations.tn_sos.tasks.sync_tn_candidates") as candidates_task:
        result = sync_tn_elections()

    statewide = Election.objects.filter(state="TN")
    assert statewide.count() >= 2
    dates = {election.election_date for election in statewide}
    assert date(2026, 8, 6) in dates
    assert date(2026, 11, 3) in dates
    # County/municipal calendar rows are deferred — nothing local gets created.
    assert not Election.objects.filter(jurisdiction_level=Election.JurisdictionLevel.LOCAL).exists()
    assert candidates_task.delay.called
    assert result["created"] >= 2


@pytest.mark.django_db
def test_sync_tn_candidates_ingests_races_and_candidates():
    election = _make_tn_election()
    list_html = (FIXTURES / "candidate_lists_2026.html").read_text()
    workbook_bytes = (FIXTURES / "candidates_us_senate_2026.xlsx").read_bytes()

    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_candidate_list_html",
        return_value=list_html,
    ), patch(
        "integrations.tn_sos.tasks.TnSosClient.download_file",
        return_value=(workbook_bytes, "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/USSenate_2026.xlsx"),
    ):
        result = sync_tn_candidates(election_pk=election.pk)

    race = Race.objects.get(election=election, office_title="United States Senate")
    assert race.source == Race.Source.TN_SOS
    assert race.candidates.filter(name="Jane Candidate", party="Republican").exists()
    assert result["created"] > 0

    election.refresh_from_db()
    workbooks = election.source_metadata["tn_candidate_workbooks"]
    assert any(entry["filename"] == "USSenate_2026.xlsx" for entry in workbooks)
    assert all("checksum" in entry for entry in workbooks)


@pytest.mark.django_db
def test_sync_tn_candidates_deduplicates_candidates_on_rerun():
    election = _make_tn_election()
    list_html = (FIXTURES / "candidate_lists_2026.html").read_text()
    workbook_bytes = (FIXTURES / "candidates_us_senate_2026.xlsx").read_bytes()

    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_candidate_list_html",
        return_value=list_html,
    ), patch(
        "integrations.tn_sos.tasks.TnSosClient.download_file",
        return_value=(workbook_bytes, "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/USSenate_2026.xlsx"),
    ):
        sync_tn_candidates(election_pk=election.pk)
        first_count = Candidate.objects.count()
        second_result = sync_tn_candidates(election_pk=election.pk)

    assert Candidate.objects.count() == first_count
    assert second_result["created"] == 0


@pytest.mark.django_db
def test_sync_tn_candidates_skips_party_executive_committee_offices():
    import io

    from openpyxl import Workbook

    election = _make_tn_election()
    list_html = (FIXTURES / "candidate_lists_2026.html").read_text()

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Office", "Candidate", "Party", "Status"])
    sheet.append(["State Executive Committeeman District 1", "Party Person", "Republican", "Signatures Approved"])
    sheet.append(["Governor", "Jane Candidate", "Republican", "Signatures Approved"])
    content = io.BytesIO()
    workbook.save(content)

    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_candidate_list_html",
        return_value=list_html,
    ), patch(
        "integrations.tn_sos.tasks.TnSosClient.download_file",
        return_value=(content.getvalue(), "https://sos-prod.tnsosgovfiles.com/s3fs-public/document/TNGOPSEC_Filed_2026-03-24.xlsx"),
    ):
        sync_tn_candidates(election_pk=election.pk)

    assert not Race.objects.filter(office_title__icontains="Executive Committee").exists()
    assert Race.objects.filter(election=election, office_title="Governor").exists()


@pytest.mark.django_db
def test_sync_tn_result_index_stores_matching_result_links():
    election = _make_tn_election(
        election_date=date(2025, 12, 2),
        name="December 2, 2025 - Special Election",
        election_type=Election.ElectionType.SPECIAL,
        status=Election.Status.RESULTS_PENDING,
        source_id="tn_sos:2025-12-02:statewide",
    )
    index_html = (FIXTURES / "results_index_sample.html").read_text()

    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_results_index_html",
        return_value=index_html,
    ):
        sync_tn_result_index()

    election.refresh_from_db()
    links = election.source_metadata["tn_result_links"]
    assert any("20251202AllbyPrecinct.xlsx" in link["url"] for link in links)

    # Rerun must not duplicate stored links.
    with patch(
        "integrations.tn_sos.tasks.TnSosClient.get_results_index_html",
        return_value=index_html,
    ):
        sync_tn_result_index()

    election.refresh_from_db()
    urls = [link["url"] for link in election.source_metadata["tn_result_links"]]
    assert len(urls) == len(set(urls))


# Mirrors the live sos.tn.gov layout (2026-10-02): the 2026-08-06 primary is headed
# "August 1, 2026" while its files are named 20260806...; the 2026-05-05 county primary's
# files are named 20260506... (posting date).
_MISDATED_INDEX_HTML = """
<ul>
  <li>August 1, 2026
    <ul>
      <li><a href="https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20260806AllbyPrecinct.xlsx">Results by Precinct Spreadsheet</a></li>
      <li><a href="https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20260806RepublicanPrimarybyCounty.pdf">By County</a></li>
    </ul>
  </li>
  <li>May 5, 2026
    <ul>
      <li><a href="https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20260506AllbyPrecinct.xlsx">Results by Precinct Spreadsheet</a></li>
    </ul>
  </li>
  <li>March 3, 2026
    <ul>
      <li><a href="https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20260303AllbyPrecinct.xlsx">Results by Precinct Spreadsheet</a></li>
    </ul>
  </li>
</ul>
"""


def _run_result_index(html):
    with patch("integrations.tn_sos.tasks.TnSosClient.get_results_index_html", return_value=html):
        sync_tn_result_index()


@pytest.mark.django_db
def test_result_index_matches_when_page_heading_date_is_wrong():
    """The August heading says Aug 1 but the election is Aug 6; the 20260806 filenames must still match."""
    august = _make_tn_election(election_date=date(2026, 8, 6))
    _run_result_index(_MISDATED_INDEX_HTML)
    august.refresh_from_db()
    urls = [entry["url"] for entry in august.source_metadata.get("tn_result_links", [])]
    assert any(url.endswith("20260806AllbyPrecinct.xlsx") for url in urls)
    assert any(url.endswith("20260806RepublicanPrimarybyCounty.pdf") for url in urls)
    assert not any("20260506" in url or "20260303" in url for url in urls)


@pytest.mark.django_db
def test_result_index_matches_when_filename_is_posting_date():
    """May files are named 20260506 but headed May 5 (the real election date)."""
    may = _make_tn_election(
        election_date=date(2026, 5, 5), name="May 5, 2026 - County Primary", source_id="tn_sos:2026-05-05:statewide",
    )
    _run_result_index(_MISDATED_INDEX_HTML)
    may.refresh_from_db()
    urls = [entry["url"] for entry in may.source_metadata.get("tn_result_links", [])]
    assert urls == ["https://sos-prod.tnsosgovfiles.com/s3fs-public/document/20260506AllbyPrecinct.xlsx"]


@pytest.mark.django_db
def test_result_index_ignores_links_far_from_any_election():
    november = _make_tn_election(
        election_date=date(2026, 11, 3), name="November 3, 2026 - General", source_id="tn_sos:2026-11-03:statewide",
    )
    _run_result_index(_MISDATED_INDEX_HTML)
    november.refresh_from_db()
    assert november.source_metadata.get("tn_result_links", []) == []


@pytest.mark.django_db
def test_result_index_skips_links_equally_close_to_two_elections():
    # Aug 1 heading / Aug 6 filename: elections on Jul 30 and Aug 8 are both 2 days away -> ambiguous.
    first = _make_tn_election(election_date=date(2026, 7, 30), source_id="tn_sos:2026-07-30:statewide")
    second = _make_tn_election(election_date=date(2026, 8, 8), source_id="tn_sos:2026-08-08:statewide")
    _run_result_index(_MISDATED_INDEX_HTML)
    for election in (first, second):
        election.refresh_from_db()
        assert not any("20260806" in e["url"] for e in election.source_metadata.get("tn_result_links", []))

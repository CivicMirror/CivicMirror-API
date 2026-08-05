from __future__ import annotations

import datetime
import io
from unittest.mock import patch

import openpyxl
import pytest

pytestmark = pytest.mark.django_db


def _build_workbook_bytes(rows: list[tuple]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_sync_ut_elections_creates_primary_and_general():
    from integrations.ut_elections.tasks import sync_ut_elections
    from elections.models import Election

    with patch("integrations.ut_elections.tasks.timezone") as mock_tz:
        mock_tz.localdate.return_value = datetime.date(2026, 8, 5)
        mock_tz.now.return_value = datetime.datetime(2026, 8, 5, tzinfo=datetime.timezone.utc)
        result = sync_ut_elections()

    assert result["created"] >= 1
    assert Election.objects.filter(state="UT", election_date=datetime.date(2026, 6, 23)).exists()
    assert Election.objects.filter(state="UT", election_date=datetime.date(2026, 11, 3)).exists()


def test_sync_ut_races_creates_races_and_candidates_for_in_scope_sections():
    from integrations.ut_elections.tasks import sync_ut_elections, sync_ut_races
    from elections.models import Election, Race, Candidate

    workbook_bytes = _build_workbook_bytes([
        ("Federal Offices", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("BEN MCADAMS", "U.S. House District 1", "Democratic", "Election Candidate"),
        ("RILEY OWEN", "U.S. House District 1", "Republican", "Election Candidate"),
        (None, None, None, None),
        ("State School Board", None, None, None),
        (None, None, None, None),
        ("Candidate", "Office", "Party", "Status"),
        ("TRACY J. NUTTALL", "State School Board Distrct 11 (Multi-County)", "Republican", "Election Candidate"),
    ])

    with patch("integrations.ut_elections.tasks.timezone") as mock_tz:
        mock_tz.localdate.return_value = datetime.date(2026, 8, 5)
        mock_tz.now.return_value = datetime.datetime(2026, 8, 5, tzinfo=datetime.timezone.utc)
        sync_ut_elections()

        with patch(
            "integrations.ut_elections.tasks.UtElectionsClient.fetch_candidate_filing_workbook",
            return_value=workbook_bytes,
        ):
            result = sync_ut_races()

    assert result["created"] == 1  # only the in-scope U.S. House District 1 race
    race = Race.objects.get(election__state="UT", office_title="U.S. House District 1")
    assert Candidate.objects.filter(race=race, name="Ben Mcadams").exists()
    assert Candidate.objects.filter(race=race, name="Riley Owen").exists()
    assert not Race.objects.filter(office_title__icontains="School Board").exists()

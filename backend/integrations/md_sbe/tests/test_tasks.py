from __future__ import annotations

import datetime
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


def test_sync_md_elections_creates_election_for_active_cycle():
    from elections.models import Election
    from integrations.md_sbe.tasks import sync_md_elections

    with patch("integrations.md_sbe.tasks.timezone") as mock_tz:
        mock_tz.localdate.return_value = datetime.date(2026, 3, 1)
        mock_tz.now.return_value = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)
        result = sync_md_elections()

    assert result["created"] >= 1
    assert Election.objects.filter(state="MD", election_date=datetime.date(2026, 6, 23)).exists()
    assert Election.objects.filter(state="MD", election_date=datetime.date(2026, 11, 3)).exists()


def test_sync_md_races_creates_races_and_candidates_for_in_scope_offices():
    from elections.models import Candidate, Election, Race
    from integrations.md_sbe.tasks import sync_md_elections, sync_md_races

    csv_text = (
        "﻿Office Name,Contest Run By District Name and Number,"
        "Candidate Ballot Last Name and Suffix,Candidate First Name and Middle Name,"
        "Office Political Party,Candidate Status,Has Related Candidate,"
        "Related Candidate Last Name and Suffix,Related Candidate First Name and Middle Name\r\n"
        "Governor / Lt. Governor,State Of Maryland,Moore,Wes,Democratic,Active,Yes,Miller,Aruna\r\n"
        "Judge of the Circuit Court,Judicial Circuit 1,Smith,Pat,,Active,\r\n"
    )

    with patch("integrations.md_sbe.tasks.timezone") as mock_tz:
        mock_tz.localdate.return_value = datetime.date(2026, 3, 1)
        mock_tz.now.return_value = datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc)
        sync_md_elections()

        with patch(
            "integrations.md_sbe.tasks.MdSbeClient.fetch_statewide_candidate_csv",
            return_value=csv_text,
        ):
            result = sync_md_races()

    assert result["created"] == 1  # only the in-scope Governor/Lt.Gov race
    race = Race.objects.get(election__state="MD", office_title="Governor / Lt. Governor")
    assert Candidate.objects.filter(race=race, name="Wes Moore / Aruna Miller").exists()
    assert not Race.objects.filter(office_title__icontains="Circuit Court").exists()

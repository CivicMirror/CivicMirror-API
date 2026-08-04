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
    assert Candidate.objects.filter(race=race, name="Wes Moore and Aruna Miller").exists()
    assert not Race.objects.filter(office_title__icontains="Circuit Court").exists()


_PRIMARY_CSV = (
    "﻿Office Name,Contest Run By District Name and Number,"
    "Candidate Ballot Last Name and Suffix,Candidate First Name and Middle Name,"
    "Office Political Party,Candidate Status,Has Related Candidate,"
    "Related Candidate Last Name and Suffix,Related Candidate First Name and Middle Name\r\n"
    "Governor / Lt. Governor,State Of Maryland,Moore,Wes,Democratic,Active,Yes,Miller,Aruna\r\n"
    "Governor / Lt. Governor,State Of Maryland,Cox,Dan,Republican,Active,Yes,Schifanelli,Gordana\r\n"
    "House of Delegates,Legislative District 1A,Buckel,Wendell,Republican,Active,\r\n"
)


def _run_sync(today: datetime.date, csv_text: str):
    from integrations.md_sbe.tasks import sync_md_elections, sync_md_races

    with patch("integrations.md_sbe.tasks.timezone") as mock_tz:
        mock_tz.localdate.return_value = today
        mock_tz.now.return_value = datetime.datetime(
            today.year, today.month, today.day, tzinfo=datetime.timezone.utc,
        )
        sync_md_elections()
        with patch(
            "integrations.md_sbe.tasks.MdSbeClient.fetch_statewide_candidate_csv",
            return_value=csv_text,
        ) as mock_fetch:
            result = sync_md_races()
    return result, mock_fetch


def test_sync_md_races_splits_primary_contests_by_party():
    """MD lists every party's candidates for a primary contest under one Office
    Name/district — without a party split, the Democratic and Republican
    Governor primaries would collapse into a single Race."""
    from elections.models import Race

    _run_sync(datetime.date(2026, 3, 1), _PRIMARY_CSV)

    gov_races = Race.objects.filter(office_title="Governor / Lt. Governor")
    assert gov_races.count() == 2
    assert {r.party for r in gov_races} == {"Democratic", "Republican"}
    assert {r.source_metadata["contest_variant"] for r in gov_races} == {
        "md:Governor / Lt. Governor::DEM",
        "md:Governor / Lt. Governor::REP",
    }
    # Party-agnostic contest_code is shared; party_code disambiguates.
    assert {r.source_metadata["contest_code"] for r in gov_races} == {
        "md:Governor / Lt. Governor:",
    }
    assert {r.source_metadata["party_code"] for r in gov_races} == {"DEM", "REP"}

    delegate = Race.objects.get(office_title="House of Delegates - Legislative District 1A")
    assert delegate.source_metadata["contest_code"] == "md:House of Delegates:01A"


def test_sync_md_races_keeps_general_contest_parties_in_one_race():
    """The general CSV lists one nominee per party competing in the SAME race."""
    from elections.models import Candidate, Race

    result, mock_fetch = _run_sync(datetime.date(2026, 8, 4), _PRIMARY_CSV)

    # After the June 23 primary, the GENERAL prefix must be used.
    assert mock_fetch.call_args.kwargs["cycle_prefix"] == "GG"
    assert mock_fetch.call_args.kwargs["phase"] == "general"

    gov_races = Race.objects.filter(office_title="Governor / Lt. Governor")
    assert gov_races.count() == 1
    assert Candidate.objects.filter(race=gov_races.first()).count() == 2
    assert "party_code" not in gov_races.first().source_metadata
    assert result["created"] == 2


def test_sync_md_races_uses_the_primary_prefix_before_the_primary():
    _, mock_fetch = _run_sync(datetime.date(2026, 3, 1), _PRIMARY_CSV)
    assert mock_fetch.call_args.kwargs["cycle_prefix"] == "GP"
    assert mock_fetch.call_args.kwargs["phase"] == "primary"

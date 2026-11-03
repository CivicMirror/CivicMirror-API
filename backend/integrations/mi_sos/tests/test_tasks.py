from unittest.mock import patch

import pytest

from elections.models import Candidate, Election, Race
from integrations.mi_sos.tasks import sync_mi_elections


@pytest.fixture
def parsed_candidate_rows():
    return [
        {
            "office_title": "GOVERNOR 4 Year Term (1) Position",
            "party": "Democratic",
            "incumbent": "",
            "filing_method": "Petitions",
            "status": "",
            "candidate_name": "Jane Candidate",
            "candidate_address": "1 Main St",
            "filed_on": "4/21/2026",
        },
        {
            "office_title": "UNITED STATES REPRESENTATIVE 7th District",
            "party": "Republican",
            "incumbent": "Incumbent",
            "filing_method": "Petitions",
            "status": "DISQ",
            "candidate_name": "John Disqualified",
            "candidate_address": "2 Main St",
            "filed_on": "4/21/2026",
        },
    ]


@pytest.mark.django_db
def test_sync_mi_elections_creates_election_race_and_candidates(parsed_candidate_rows):
    with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls, \
         patch("integrations.mi_sos.tasks.parse_boe_candidate_listing", return_value=parsed_candidate_rows):
        client_cls.return_value.fetch_candidate_listing.return_value = "<html>fixture</html>"
        client_cls.return_value.fetch_votehistory_page.return_value = "<html>no dropdown</html>"
        result = sync_mi_elections()

    assert result["created"] >= 3
    election = Election.objects.get(state="MI", election_type="primary", election_date="2026-08-04")
    race = Race.objects.get(election=election, office_title="Governor")
    candidate = Candidate.objects.get(race=race, name="Jane Candidate")
    assert candidate.party == "DEM"
    assert candidate.candidate_status == Candidate.CandidateStatus.RUNNING

    house_race = Race.objects.get(election=election, office_title="U.S. House - District 7")
    disq = Candidate.objects.get(race=house_race, name="John Disqualified")
    assert disq.candidate_status == Candidate.CandidateStatus.DISQUALIFIED
    assert disq.source_metadata["mi_candidate_status_raw"] == "DISQ"


@pytest.mark.django_db
def test_sync_mi_elections_marks_absent_running_candidate_withdrawn(parsed_candidate_rows):
    with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls, \
         patch("integrations.mi_sos.tasks.parse_boe_candidate_listing", return_value=parsed_candidate_rows):
        client_cls.return_value.fetch_candidate_listing.return_value = "<html>fixture</html>"
        client_cls.return_value.fetch_votehistory_page.return_value = "<html>no dropdown</html>"
        sync_mi_elections()

    election = Election.objects.get(state="MI", election_type="primary", election_date="2026-08-04")
    race = Race.objects.get(election=election, office_title="Governor")
    stale = Candidate.objects.create(
        race=race,
        name="Stale Candidate",
        party="DEM",
        candidate_status=Candidate.CandidateStatus.RUNNING,
    )

    with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls, \
         patch("integrations.mi_sos.tasks.parse_boe_candidate_listing", return_value=parsed_candidate_rows):
        client_cls.return_value.fetch_candidate_listing.return_value = "<html>fixture</html>"
        client_cls.return_value.fetch_votehistory_page.return_value = "<html>no dropdown</html>"
        sync_mi_elections()

    stale.refresh_from_db()
    assert stale.candidate_status == Candidate.CandidateStatus.WITHDRAWN


@pytest.mark.django_db
def test_sync_mi_elections_ingests_the_real_general_listing_end_to_end():
    """From the captured Nov 3, 2026 BOE listing to races Michigan's results can match.

    Before the parser fix this produced judicial races only: Michigan's record held
    41 judicial contests and no Governor, U.S. Senate, Secretary of State or
    Attorney General race at all.
    """
    from pathlib import Path

    from integrations.mi_sos.mappers import result_office_title

    fixture = (
        Path(__file__).parent / "fixtures" / "boe_candidate_listing_2026_general.html"
    ).read_text(encoding="utf-8")

    with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls:
        client_cls.return_value.fetch_candidate_listing.return_value = fixture
        client_cls.return_value.fetch_votehistory_page.return_value = "<html>no dropdown</html>"
        sync_mi_elections()

    election = Election.objects.get(state="MI", election_type="general", election_date="2026-11-03")
    titles = set(Race.objects.filter(election=election).values_list("office_title", flat=True))
    assert {"Governor", "U.S. Senate", "Secretary of State"} <= titles

    governor = Race.objects.get(election=election, office_title="Governor")
    assert governor.geography_scope == "statewide"
    tickets = dict(Candidate.objects.filter(race=governor).values_list("name", "party"))
    assert tickets["Benson, Jocelyn / Brinks, Winnie"] == "DEM"
    assert tickets["James, John / DeBoyer, Jay"] == "REP"
    assert tickets["Hudson, Anthony / Parmenter, Beau"] == "LIB"

    senate = Race.objects.get(election=election, office_title="U.S. Senate")
    assert senate.geography_scope == "federal"
    parties = set(Candidate.objects.filter(race=senate).values_list("party", flat=True))
    assert {"DEM", "REP"} <= parties
    # UST, not the truncated "U.S" the old abbreviation fallback produced.
    assert "UST" in parties

    # The incumbency marker must land on the candidate, not in the party field.
    incumbents = Candidate.objects.filter(race__election=election, incumbent=True)
    assert incumbents.exists()
    assert set(incumbents.values_list("party", flat=True)) == {""}

    # The point of the fix: a results contest title keys to the race just created.
    assert result_office_title("UNITED STATES SENATOR") == senate.office_title
    assert result_office_title("GOVERNOR") == governor.office_title


@pytest.mark.django_db
def test_resyncing_the_general_listing_is_idempotent_and_backfills_scope():
    """A second sync must update in place, not duplicate Michigan's ballot.

    Also the backfill path for the 41 judicial races already in production with a
    blank geography_scope: re-syncing writes it, because mi_sos owns the field.
    """
    from pathlib import Path

    fixture = (
        Path(__file__).parent / "fixtures" / "boe_candidate_listing_2026_general.html"
    ).read_text(encoding="utf-8")

    def _run():
        with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls:
            client_cls.return_value.fetch_candidate_listing.return_value = fixture
            client_cls.return_value.fetch_votehistory_page.return_value = "<html>no dropdown</html>"
            sync_mi_elections()

    _run()
    election = Election.objects.get(state="MI", election_type="general", election_date="2026-11-03")
    first_races = set(Race.objects.filter(election=election).values_list("pk", flat=True))
    first_candidates = Candidate.objects.filter(race__election=election).count()

    # Simulate the production state: scope blank, as mi_sos used to leave it.
    Race.objects.filter(election=election).update(geography_scope="")

    _run()

    assert set(Race.objects.filter(election=election).values_list("pk", flat=True)) == first_races
    assert Candidate.objects.filter(race__election=election).count() == first_candidates
    assert not Race.objects.filter(election=election, geography_scope="").exists()


# ---------------------------------------------------------------------------
# MVIC election-id discovery
# ---------------------------------------------------------------------------

_VOTEHISTORY_HTML = """
<html><body>
  <select id="ElectionDateId">
    <option value="">Select an election</option>
    <option value="705">5/5/2026 - MAY CONSOLIDATED</option>
    <option value="712">11/3/2026 - GENERAL ELECTION</option>
  </select>
</body></html>
"""


def _sync_with(votehistory=None, listing="<html>no candidates</html>", side_effect=None):
    with patch("integrations.mi_sos.tasks.MiSosClient") as client_cls:
        client = client_cls.return_value
        client.fetch_candidate_listing.return_value = listing
        if side_effect is not None:
            client.fetch_votehistory_page.side_effect = side_effect
        else:
            client.fetch_votehistory_page.return_value = votehistory
        sync_mi_elections()


@pytest.mark.django_db
def test_discovery_writes_the_mvic_id_onto_the_matching_election():
    """results/adapters/mi.py fetches nothing without this key, and nothing wrote it."""
    _sync_with(votehistory=_VOTEHISTORY_HTML)

    general = Election.objects.get(state="MI", election_type="general", election_date="2026-11-03")
    assert general.source_metadata["mi_mvic_election_id"] == "712"
    # The BOE keys must survive alongside it.
    assert general.source_metadata["mi_boe_election_type"] == "GEN"

    # The August primary is not in the dropdown, so it gets no id rather than a wrong one.
    primary = Election.objects.get(state="MI", election_type="primary", election_date="2026-08-04")
    assert "mi_mvic_election_id" not in primary.source_metadata


@pytest.mark.django_db
def test_candidate_sync_survives_mvic_being_unreachable():
    """MVIC and the BOE are different hosts; a CF solver outage must not stop the ballot."""
    from pathlib import Path

    from core.cf_solver import CfSolverUnavailableError

    fixture = (
        Path(__file__).parent / "fixtures" / "boe_candidate_listing_2026_general.html"
    ).read_text(encoding="utf-8")

    _sync_with(listing=fixture, side_effect=CfSolverUnavailableError("CF_SOLVER_URL is not configured"))

    election = Election.objects.get(state="MI", election_type="general", election_date="2026-11-03")
    assert "mi_mvic_election_id" not in (election.source_metadata or {})
    assert Race.objects.filter(election=election, office_title="Governor").exists()


@pytest.mark.django_db
def test_a_later_sync_fills_in_an_id_mvic_had_not_published_yet():
    """MVIC may not list an election until its results start posting."""
    _sync_with(votehistory="<html><body>no dropdown</body></html>")
    general = Election.objects.get(state="MI", election_type="general", election_date="2026-11-03")
    assert "mi_mvic_election_id" not in (general.source_metadata or {})

    _sync_with(votehistory=_VOTEHISTORY_HTML)
    general.refresh_from_db()
    assert general.source_metadata["mi_mvic_election_id"] == "712"


@pytest.mark.django_db
def test_discovery_ignores_undatable_dropdown_entries():
    _sync_with(votehistory="""
        <html><body><select id="ElectionDateId">
          <option value="900">No date here</option>
          <option value="712">11/3/2026 - GENERAL ELECTION</option>
        </select></body></html>
    """)

    general = Election.objects.get(state="MI", election_type="general", election_date="2026-11-03")
    assert general.source_metadata["mi_mvic_election_id"] == "712"

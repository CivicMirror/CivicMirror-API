import os
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.nm import NewMexicoAdapter, NmBproRetryableError
from results.adapters.nm_parse import parse_election_wide_csv

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_election_wide_csv_extracts_all_rows():
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    assert len(rows) == 22


def test_parse_election_wide_csv_qualifies_colliding_office_titles():
    """Two different RaceIDs both named 'Mayor'/'MAYOR' must not collapse into
    one office_title. On the bootstrap path this is redundant with contest_code
    -based source_identity (see test_bootstrap_creates_separate_races_for_
    colliding_office_titles's docstring), but results/tasks.py::
    _process_race_results also falls back to matching pre-existing races by
    office_title alone when they lack contest_code metadata — an unqualified
    'Mayor' would genuinely collide there."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)

    alamo_titles = {r.office_title for r in rows if r.raw["contest_code"] == "10083"}
    abq_titles = {r.office_title for r in rows if r.raw["contest_code"] == "10144"}

    assert alamo_titles == {"ALAMO CITY DISTRICT- ALL — Mayor"}
    assert abq_titles == {"CITY OF ALBUQUERQUE — MAYOR"}
    assert alamo_titles != abq_titles


def test_parse_election_wide_csv_matches_the_cross_referenced_test_contest():
    """RaceID 10087 / CandidateID 17700 is the contest cross-referenced
    throughout NM-Election_ResearchV4.md's crosswalk tables — 3,573 votes."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    overstreet = next(r for r in rows if r.raw["contest_code"] == "10087")

    assert overstreet.candidate_name == "DAVID MATTHEW OVERSTREET"
    assert overstreet.vote_count == 3573
    assert overstreet.vote_pct == 100.0
    assert overstreet.office_title == "ALAMO CITY DISTRICT- ALL — Municipal Judge"
    assert overstreet.jurisdiction_fragment == "ALAMO CITY DISTRICT- ALL"
    assert overstreet.result_type == "unofficial"
    assert overstreet.is_winner is None
    assert overstreet.is_write_in_aggregate is False


def test_parse_election_wide_csv_routes_yes_no_ids_to_option_label():
    """CandidateID 9001/9002 are generic, globally-reused Yes/No choice IDs —
    must route to option_label (a ballot-measure choice), never candidate_name."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)

    yes_rows = [r for r in rows if r.option_label == "Yes"]
    no_rows = [r for r in rows if r.option_label == "No"]
    assert len(yes_rows) == 3
    assert len(no_rows) == 3
    for row in yes_rows + no_rows:
        assert row.candidate_name is None

    dora_yes = next(r for r in yes_rows if r.raw["contest_code"] == "1188")
    assert dora_yes.vote_count == 63
    assert dora_yes.office_title == "DORA MUNICIPAL SCHOOL DISTRICT — Bond Question : Dora  General Obligation Bond Question"


def test_parse_election_wide_csv_falls_back_to_bare_race_name_when_area_num_blank():
    """RaceID 1255 has a blank AreaNum (county-level measure) — office_title
    should fall back to the bare RaceName rather than a dangling '— ' prefix."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    curry_yes = next(r for r in rows if r.raw["contest_code"] == "1255" and r.option_label == "Yes")

    assert curry_yes.office_title.startswith("COUNTY LOCAL OPTION GROSS RECEIPTS TAX QUESTION")
    assert " — " not in curry_yes.office_title[:5]
    assert curry_yes.jurisdiction_fragment == ""
    assert curry_yes.vote_count == 1987


def test_parse_election_wide_csv_truncates_long_office_titles_to_fit_the_db_column():
    """Race.office_title is a CharField(max_length=255). 108 of the 599 real
    races in the full captured election have a RaceName exceeding that limit
    (full ballot-measure legal text, up to 636 chars observed) — SQLite
    doesn't enforce CharField length so this only bites against a real
    Postgres database (confirmed: CI failed on this exact row with
    psycopg2.errors.StringDataRightTruncation before the fix)."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    tatum_rows = [r for r in rows if r.raw["contest_code"] == "1304"]

    assert len(tatum_rows) == 2
    for row in tatum_rows:
        assert len(row.office_title) == 255
        assert row.office_title.startswith("TATUM MUNICIPAL SCHOOL DISTRICT — TATUM MUNICIPAL SCHOOLS")
        assert row.office_title.endswith("…")

    yes_row = next(r for r in tatum_rows if r.option_label == "Yes")
    assert yes_row.vote_count == 189


def test_parse_election_wide_csv_passes_through_named_write_in_without_aggregation():
    """MO/MD each needed special write-in handling; NM doesn't — declared
    write-ins already appear as ordinary, individually-itemized rows with
    '(write in)' in the display name and a real vote count."""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    write_in = next(r for r in rows if r.raw["contest_code"] == "10396")

    assert write_in.candidate_name == "MICHAEL CRAIG THOMPSON (write in)"
    assert write_in.vote_count == 159
    assert write_in.is_write_in_aggregate is False


def test_parse_election_wide_csv_handles_vote_for_multiple_races():
    """VoteFor=2 races (multi-seat) are parsed like any other — one ResultRow
    per candidate, no special-casing. (In the wider real Media.csv, races with
    more candidates than seats can have per-race percentages summing above
    100% — e.g. RaceID 10204, 10 candidates for 2 seats, sums to ~200% — but
    this fixture's example has exactly as many candidates as seats, so it
    sums to exactly 100%; the parser doesn't validate or enforce any
    particular sum either way, it just passes each row's percentage through.)"""
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    councilor_rows = [r for r in rows if r.raw["contest_code"] == "10150"]

    assert len(councilor_rows) == 2
    assert {r.candidate_name for r in councilor_rows} == {"JAMES DEE WILEY", "YVONNE KAY MILLIGAN"}
    wiley = next(r for r in councilor_rows if r.candidate_name == "JAMES DEE WILEY")
    milligan = next(r for r in councilor_rows if r.candidate_name == "YVONNE KAY MILLIGAN")
    assert wiley.vote_count == 32
    assert milligan.vote_count == 56


def test_parse_election_wide_csv_sets_contest_code_and_party_code_in_raw():
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    overstreet = next(r for r in rows if r.raw["contest_code"] == "10087")
    assert overstreet.raw == {"contest_code": "10087", "party_code": ""}


@patch("results.adapters.nm.requests.get")
def test_fetch_csv_bytes_sends_browser_user_agent(mock_get):
    response = MagicMock(status_code=200, content=b"RaceID,RaceName,PartyCode\n10083,Mayor,\n")
    mock_get.return_value = response

    result = NewMexicoAdapter()._fetch_csv_bytes("https://electionresults.sos.nm.gov/example.aspx")

    assert result == b"RaceID,RaceName,PartyCode\n10083,Mayor,\n"
    called_headers = mock_get.call_args.kwargs["headers"]
    assert "Mozilla" in called_headers["User-Agent"]


@patch("results.adapters.nm.requests.get")
def test_fetch_csv_bytes_rejects_non_csv_content(mock_get):
    """BPro's ASP.NET WebForms shell can return an HTML error page with a
    200 status — must be detected by content (expected CSV header), never
    trusted by status code alone."""
    response = MagicMock(status_code=200, content=b"<!DOCTYPE html><html>Server Error</html>")
    mock_get.return_value = response

    with pytest.raises(NmBproRetryableError):
        NewMexicoAdapter()._fetch_csv_bytes("https://electionresults.sos.nm.gov/example.aspx")


@pytest.mark.django_db
@patch("results.adapters.nm.NewMexicoAdapter._fetch_csv_bytes")
def test_fetch_results_parses_real_fixture_into_rows(mock_fetch):
    from elections.models import Election

    election = Election.objects.create(
        name="2025 Regular Local Election",
        election_date=date(2025, 11, 4),
        jurisdiction_level=Election.JurisdictionLevel.LOCAL,
        state="NM",
        source_id="nm-2025-local-2897",
        status=Election.Status.RESULTS_PENDING,
    )
    mock_fetch.return_value = _load_fixture("nm_media_excerpt.csv").encode("utf-8")

    result = NewMexicoAdapter().fetch_results(election_date=election.election_date, election_id=election.pk)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 22
    assert any(r.office_title == "ALAMO CITY DISTRICT- ALL — Municipal Judge" for r in result.rows)


@pytest.mark.django_db
@patch("results.adapters.nm.NewMexicoAdapter._fetch_csv_bytes")
def test_fetch_results_returns_unchanged_when_checksum_matches_cache(mock_fetch):
    from django.core.cache import cache

    from elections.models import Election

    election = Election.objects.create(
        name="2025 Regular Local Election",
        election_date=date(2025, 11, 4),
        jurisdiction_level=Election.JurisdictionLevel.LOCAL,
        state="NM",
        source_id="nm-2025-local-2897-b",
        status=Election.Status.RESULTS_PENDING,
    )
    mock_fetch.return_value = _load_fixture("nm_media_excerpt.csv").encode("utf-8")

    adapter = NewMexicoAdapter()
    first = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    cache.set(adapter.version_cache_key(election.pk), first.source_version)

    second = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    assert second.unchanged is True
    assert second.rows == []


@pytest.mark.django_db
def test_fetch_results_returns_empty_for_missing_election():
    result = NewMexicoAdapter().fetch_results(election_date=date(2025, 11, 4), election_id=999999)
    assert result.rows == []
    assert result.mapping_confidence == "none"


@pytest.mark.django_db
def test_bootstrap_creates_separate_races_for_colliding_office_titles():
    """Exercises results/tasks.py::_bootstrap_races_from_results end-to-end
    against real fixture data — the path NM hits on an election's first-ever
    ingest, since hyper-local municipal races won't already exist via Google
    Civic API sync. Verifies it produces correct, separate Race/Candidate/
    MeasureOption rows, including for two contests that happen to share a
    similar office name (Alamo's "Mayor" vs Albuquerque's "MAYOR").

    Note: in this code path, what actually keeps the two Mayor contests from
    merging is `_bootstrap_races_from_results` grouping rows by
    `(office_title, source_identity)`, where `source_identity` is derived
    from `row.raw["contest_code"]` (the BPro RaceID, e.g. 10083 vs 10144) —
    nm_parse.py sets a distinct contest_code on every row, so the two contests
    are disambiguated regardless of the office_title qualification. The
    office_title qualification (`f"{AreaNum} — {RaceName}"`, Task 1) remains
    valuable defense-in-depth for a different path — _process_race_results's
    fallback title-matching against *pre-existing* races that lack
    contest_code metadata — which this test does not exercise. That's an
    accepted gap for now: no other NM race-creation adapter exists yet that
    would populate such pre-existing races."""
    from elections.models import Candidate, Election, Race
    from results.adapters.base import AdapterResult
    from results.adapters.nm_parse import parse_election_wide_csv
    from results.tasks import _bootstrap_races_from_results

    election = Election.objects.create(
        name="2025 Regular Local Election",
        election_date=date(2025, 11, 4),
        jurisdiction_level=Election.JurisdictionLevel.LOCAL,
        state="NM",
        source_id="nm-2025-local-2897-bootstrap",
        status=Election.Status.RESULTS_PENDING,
    )
    rows = parse_election_wide_csv(_load_fixture("nm_media_excerpt.csv"))
    adapter_result = AdapterResult(rows=rows, source_url="https://example.test", mapping_confidence="full")

    races = _bootstrap_races_from_results(election, adapter_result, "NM")

    alamo_mayor = Race.objects.get(election=election, office_title="ALAMO CITY DISTRICT- ALL — Mayor")
    abq_mayor = Race.objects.get(election=election, office_title="CITY OF ALBUQUERQUE — MAYOR")
    assert alamo_mayor.pk != abq_mayor.pk

    alamo_candidates = set(Candidate.objects.filter(race=alamo_mayor).values_list("name", flat=True))
    abq_candidates = set(Candidate.objects.filter(race=abq_mayor).values_list("name", flat=True))
    assert alamo_candidates == {"JASON R BALDWIN", "LATANYA M BOYCE", "SHARON A MCDONALD", "TED M MORGAN", "RICHARD R COTA"}
    assert abq_candidates == {"DARREN WHITE", "DANIEL CHAVEZ", "LOUIE SANCHEZ", "TIMOTHY M KELLER", "ALEXANDER MAMORU MAX UBALLEZ", "MAYLING M ARMIJO", "EDDIE R VARELA"}
    assert alamo_candidates.isdisjoint(abq_candidates)

    dora_bond = Race.objects.get(
        election=election,
        office_title="DORA MUNICIPAL SCHOOL DISTRICT — Bond Question : Dora  General Obligation Bond Question",
    )
    assert dora_bond.race_type == Race.RaceType.MEASURE

    municipal_judge = Race.objects.get(election=election, office_title="ALAMO CITY DISTRICT- ALL — Municipal Judge")
    assert municipal_judge.race_type == Race.RaceType.CANDIDATE
    assert Candidate.objects.get(race=municipal_judge).name == "DAVID MATTHEW OVERSTREET"

    assert len(races) == Race.objects.filter(election=election).count()

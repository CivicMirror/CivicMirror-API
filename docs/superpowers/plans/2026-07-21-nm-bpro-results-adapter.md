# New Mexico (NM) BPro TotalVote Results Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship NM's Stage 2 (current/live results) adapter parsing BPro TotalVote's election-wide CSV export, validated against the historical `eid=2897` (2025 Regular Local Election) capture, so NM reaches "Results Coverage Only" tier (same tier as MD/MO/NC/NY/CA) with races bootstrapped directly from result rows (see below — unlike MD/MO, NM's races are hyper-local and won't already exist via Google Civic API).

**Architecture:** New Mexico runs two unrelated public election-data systems (BPro TotalVote ENR for live/current results, Civera ElectionStats for historical GraphQL-backed data — see `docs/state-research/NM/NM-Election_ResearchV4.md`). This plan builds **only the BPro side**, mirroring the flat-combined-totals-CSV pattern already used by `results/adapters/md.py`/`md_aggregate.py` and `results/adapters/mo.py`/`mo_parse.py`: fetch one file (BPro's election-wide CSV, one row per race+candidate/choice), parse it, emit `ResultRow`s. No separate `integrations.nm_*` Django app is needed (mirrors `mo.py`'s no-app precedent) — just `results/adapters/nm_parse.py` (pure parsing) + `results/adapters/nm.py` (fetch/orchestration), registered via the existing `@register` decorator. Civera is tracked separately in GitHub issue #84 and is explicitly out of scope here.

**Tech Stack:** Django, `requests`, Python's stdlib `csv` module (this is a well-formed, properly-quoted CSV — no regex parsing needed, unlike Missouri's PDF-text extraction).

## Global Constraints

- **No office allowlist for this build** — unlike MD/MO (whose source files mixed many unrelated offices/elections needing scope-narrowing), NM's election-wide CSV is already scoped to exactly one election (`eid=2897`) by construction; every row in a successful fetch is a legitimate result for that election. Parse everything.
- **Office-title qualification is required and is the one non-obvious design decision in this plan.** NM's captured election is hyper-local: verified directly against the real `Media.csv` (297KB, 1578 rows), there are **599 distinct `RaceID`s but only 229 distinct `RaceName`s** — `"Mayor"` alone is the `RaceName` for 49 different `RaceID`s across 49 different cities. Every row carries `raw={"contest_code": RaceID, "party_code": PartyCode}`, and `results/tasks.py::_bootstrap_races_from_results` groups result rows by `(office_title, source_identity)` where `source_identity` is derived from `contest_code` — so on the bootstrap path (this build's primary real-world path), the distinct `RaceID`s already keep the two "Mayor" contests from merging, independent of the `office_title` string. The qualification's real, still-necessary purpose is defense-in-depth for a *different* path: `results/tasks.py::_process_race_results`'s fallback title-matching against **pre-existing** races that lack `contest_code` metadata (`_office_title_key` comparison) — a bare `"Mayor"` `office_title` there genuinely would let two cities' races collide, since that fallback matches on title alone. `results/adapters/ct.py` already solved this exact problem for Connecticut's same-named municipal offices via `_build_office_town_map`, qualifying titles as `f"{town_name} — {base_title}"` (`ct.py:210`). This plan follows that precedent exactly: `office_title = f"{AreaNum} — {RaceName}"` (bare `RaceName` when `AreaNum` is blank — verified safe: all 8 blank-`AreaNum` rows in the real file are county-level ballot measures whose `RaceName` is already a long, globally-unique question text). That fallback-matching path is not exercised by this plan's tests — see "Follow-up work."
- **`vote_pct` conversion:** BPro's `CandidatePercentage` column is a 0–1 fraction (e.g. `0.357836338418863`). The repo convention (confirmed via `results/adapters/me.py:247`, `votes/total*100`) stores `ResultRow.vote_pct` on a 0–100 scale — multiply by 100. Getting this backwards silently stores percentages 100x too small.
- **`result_type = "unofficial"`**, not `"official"`. BPro is explicitly a live/election-night reporting system, and the research doc's own Section 10 documents a real label inconsistency for this exact election (the public page says "Official Results" while the Excel export for the same election says "Unofficial Special Election Results"). This matches the repo convention already used by other live-source adapters — `fl.py`, `wa.py`, `pa.py`, `mn.py`, `nj.py`, `tx.py`, `enhanced_voting.py` all use `"unofficial"` — as opposed to MD/MO's `"official"` (both pull from certified archives).
- **No comma-stripping or blank-handling needed for `CandidateVotes`** — verified 0/1578 real rows have commas or blank values in this column (simpler than Missouri's PDF-extracted numbers). Still parse defensively (fall back to `0` on a `ValueError`) since this is unverified for elections other than the one captured.
- **The Cloudflare/bot-protection status of `electionresults.sos.nm.gov` is UNVERIFIED.** Missouri's SOS needed a browser `User-Agent` header (confirmed via direct testing); Maryland's did not. This plan sends one defensively, but confirming this live is the first thing to check when implementing Task 2 — do not assume either way.
- **All fixture data in this plan is real, real, locally-downloaded data** — `docs/state-research/NM/Media.csv`, captured 2026-07-21, a live BPro election-wide CSV export for `eid=2897` (the 2025 Regular Local Election). No synthetic/invented data.
- No live network calls in the test suite itself — all HTTP is mocked using the captured fixture text.
- No new Celery task, internal endpoint, or `TASK_LOCKS` entry — Stage-2-only adapters are picked up automatically via `results.adapters.registry.get_adapter()` once registered, same as MD/MO.
- Run tests with `pytest --no-migrations` (local test-DB creation breaks on an unrelated bad migration in this environment).
- Keep new test-file imports at the top of the file from the start — a prior task in a different, already-merged feature failed CI on a mid-file-import ruff `E402` error.
- Full research context: `docs/state-research/NM/NM-Election_ResearchV4.md`. Civera (deferred) is tracked in GitHub issue #84.

---

### Task 1: `nm_parse.py` — parse BPro election-wide CSV text into `ResultRow`s

**Files:**
- Create: `backend/results/adapters/nm_parse.py`
- Create: `backend/results/tests/fixtures/nm_media_excerpt.csv` (real excerpt — content given below)
- Test: `backend/results/tests/test_nm_adapter.py` (this task's tests only — Tasks 2/3 add more to the same file)

**Interfaces:**
- Produces: `parse_election_wide_csv(csv_text: str) -> list[ResultRow]`. Consumed by Task 2's `NewMexicoAdapter.fetch_results`. Uses the existing `ResultRow` dataclass from `results/adapters/base.py` — do not modify that file, just import from it.

The fixture file below is a real 20-row excerpt from `docs/state-research/NM/Media.csv` (captured 2026-07-21), chosen to exercise every parsing rule: the cross-referenced test contest (`RaceID=10087`, Overstreet, 3,573 votes — this exact row appears throughout the research doc's crosswalk tables), two different `RaceID`s both named `"Mayor"`/`"MAYOR"` (the office-title collision case — `10083` "ALAMO CITY DISTRICT- ALL" vs `10144` "CITY OF ALBUQUERQUE"), a Yes/No measure pair (`RaceID=1188`), a second Yes/No measure pair with a long globally-unique question as `RaceName` and blank `AreaNum` (`RaceID=1255`), a named write-in candidate (`RaceID=10396`, `"MICHAEL CRAIG THOMPSON (write in)"`), and a vote-for-multiple race (`RaceID=10150`, `VoteFor=2`).

- [ ] **Step 1: Save the fixture file**

```bash
mkdir -p backend/results/tests/fixtures
cat > backend/results/tests/fixtures/nm_media_excerpt.csv << 'EOF'
RaceID,RaceName,PartyCode,AreaNum,CandidateID,CandidateName,VoteFor,CandidateVotes,CandidatePercentage,PrecinctsReporting,CandidateAbsenteeVotes,CandidateElectionDayVotes,CandidateEarlyVotes
10083,"Mayor","","ALAMO CITY DISTRICT- ALL",17580,"JASON R BALDWIN",1,1548,0.357836338418863,33/33,,,,
10144,"MAYOR","","CITY OF ALBUQUERQUE",18014,"DARREN WHITE",1,41137,0.306473362289256,611/611,,,,
10144,"MAYOR","","CITY OF ALBUQUERQUE",17935,"DANIEL CHAVEZ",1,1366,0.0101767900645921,611/611,,,,
10083,"Mayor","","ALAMO CITY DISTRICT- ALL",17457,"LATANYA M BOYCE",1,672,0.155339805825243,33/33,,,,
10083,"Mayor","","ALAMO CITY DISTRICT- ALL",17720,"SHARON A MCDONALD",1,1712,0.395746648173833,33/33,,,,
10083,"Mayor","","ALAMO CITY DISTRICT- ALL",18218,"TED M MORGAN",1,206,0.0476190476190476,33/33,,,,
10083,"Mayor","","ALAMO CITY DISTRICT- ALL",17504,"RICHARD R COTA",1,188,0.0434581599630143,33/33,,,,
10144,"MAYOR","","CITY OF ALBUQUERQUE",17956,"LOUIE SANCHEZ",1,8647,0.0644207201233731,611/611,,,,
10144,"MAYOR","","CITY OF ALBUQUERQUE",18272,"TIMOTHY M KELLER",1,47911,0.356940108919964,611/611,,,,
10144,"MAYOR","","CITY OF ALBUQUERQUE",18021,"ALEXANDER MAMORU MAX UBALLEZ",1,25213,0.187838512370834,611/611,,,,
10144,"MAYOR","","CITY OF ALBUQUERQUE",17945,"MAYLING M ARMIJO",1,7673,0.0571643559045498,611/611,,,,
10144,"MAYOR","","CITY OF ALBUQUERQUE",17938,"EDDIE R VARELA",1,2280,0.0169861503274304,611/611,,,,
10396,"Mayor","","MAGDALENA ",18787,"MICHAEL CRAIG THOMPSON (write in)",1,159,1,2/2,,,,
10150,"City Councilor","","RESERVE VILLAGE",17444,"JAMES DEE WILEY",2,32,0.363636363636364,1/1,,,,
10150,"City Councilor","","RESERVE VILLAGE",18241,"YVONNE KAY MILLIGAN",2,56,0.636363636363636,1/1,,,,
10087,"Municipal Judge","","ALAMO CITY DISTRICT- ALL",17700,"DAVID MATTHEW OVERSTREET",1,3573,1,33/33,,,,
1188,"Bond Question : Dora  General Obligation Bond Question","","DORA MUNICIPAL SCHOOL DISTRICT",9001,"Yes",1,63,0.707865168539326,2/2,,,,
1188,"Bond Question : Dora  General Obligation Bond Question","","DORA MUNICIPAL SCHOOL DISTRICT",9002,"No",1,26,0.292134831460674,2/2,,,,
1255,"COUNTY LOCAL OPTION GROSS RECEIPTS TAX QUESTION: Shall Curry County impose a county-wide local option gross receipts tax in the amount of thirteen hundredths percent (0.130%) the revenues of which shall be used for funding capital improvements, including design, acquisition, construction, equipping, and improvement of parks and recreational facilities to be located in the City of Clovis, New Mexico, and which tax shall expire twenty-five years after imposition? - Curry - Curry","","",9001,"Yes",1,1987,0.467969853980217,43/43,,,,
1255,"COUNTY LOCAL OPTION GROSS RECEIPTS TAX QUESTION: Shall Curry County impose a county-wide local option gross receipts tax in the amount of thirteen hundredths percent (0.130%) the revenues of which shall be used for funding capital improvements, including design, acquisition, construction, equipping, and improvement of parks and recreational facilities to be located in the City of Clovis, New Mexico, and which tax shall expire twenty-five years after imposition? - Curry - Curry","","",9002,"No",1,2259,0.532030146019783,43/43,,,,
EOF
```

- [ ] **Step 2: Write the failing test**

```python
# backend/results/tests/test_nm_adapter.py
import os

from results.adapters.nm_parse import parse_election_wide_csv

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_parse_election_wide_csv_extracts_all_rows():
    text = _load_fixture("nm_media_excerpt.csv")
    rows = parse_election_wide_csv(text)
    assert len(rows) == 20


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
    assert len(yes_rows) == 2
    assert len(no_rows) == 2
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest results/tests/test_nm_adapter.py --no-migrations -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'results.adapters.nm_parse'`

- [ ] **Step 4: Write the implementation**

```python
# backend/results/adapters/nm_parse.py
"""
Parser for BPro TotalVote's election-wide CSV export (New Mexico SOS).

New Mexico runs two unrelated public election-data systems (see
docs/state-research/NM/NM-Election_ResearchV4.md): BPro TotalVote ENR for
live/current results (this module) and Civera ElectionStats for historical
GraphQL-backed data (deferred, tracked in GitHub issue #84).

The election-wide CSV (resultsCSV.aspx?text=All&type=STATE&map=CTY&eid=...)
gives one row per (race, candidate-or-ballot-choice) with combined
(non-precinct) vote totals for every race in one election — no aggregation
across files is needed, unlike Maryland's per-county CSVs.

Two things this parser must get right that Maryland/Missouri didn't need to:

1. Office-title collisions: NM's captured election is hyper-local (mayors,
   municipal judges, school boards, city councilors across dozens of towns).
   The same RaceName (e.g. "Mayor") is reused by dozens of unrelated
   RaceIDs. office_title is qualified as "{AreaNum} — {RaceName}" (falling
   back to bare RaceName when AreaNum is blank) to avoid
   results.tasks._bootstrap_races_from_results collapsing unrelated cities'
   races into one, mirroring results/adapters/ct.py's _build_office_town_map
   precedent for the identical problem.
2. Generic Yes/No choice IDs: CandidateID 9001/9002 are reused across every
   ballot-measure row in the file to mean "Yes"/"No" — routed to
   option_label, never candidate_name, and scoped per-row by contest_code
   (RaceID) since the ID itself is not globally unique to one measure.

Percentages arrive as a 0-1 fraction; ResultRow.vote_pct is stored on a
0-100 scale (repo convention, see results/adapters/me.py) — multiplied here.

result_type is "unofficial": BPro is a live/election-night system, and the
research doc documents a real label inconsistency for this exact election
(public page says "Official Results", the Excel export for the same
election says "Unofficial Special Election Results") — this matches other
live-source adapters (fl.py, wa.py, pa.py, mn.py, nj.py, tx.py), not
Maryland/Missouri's "official" (both pull from certified archives).

No Winner column exists in this CSV — is_winner is always None.
"""
from __future__ import annotations

import csv
import io

from .base import ResultRow

_YES_NO_CANDIDATE_IDS = frozenset({"9001", "9002"})


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_int(value: str | None) -> int:
    cleaned = _clean(value)
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


def parse_election_wide_csv(csv_text: str) -> list[ResultRow]:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[ResultRow] = []

    for raw_row in reader:
        race_id = _clean(raw_row.get("RaceID"))
        race_name = _clean(raw_row.get("RaceName"))
        area_num = _clean(raw_row.get("AreaNum"))
        candidate_id = _clean(raw_row.get("CandidateID"))
        candidate_name = _clean(raw_row.get("CandidateName"))
        party_code = _clean(raw_row.get("PartyCode"))

        if not race_id or not race_name:
            continue

        office_title = f"{area_num} — {race_name}" if area_num else race_name
        is_yes_no = candidate_id in _YES_NO_CANDIDATE_IDS

        pct_raw = _clean(raw_row.get("CandidatePercentage"))
        try:
            vote_pct = float(pct_raw) * 100 if pct_raw else None
        except ValueError:
            vote_pct = None

        rows.append(
            ResultRow(
                candidate_name=None if is_yes_no else candidate_name,
                option_label=candidate_name if is_yes_no else None,
                vote_count=_parse_int(raw_row.get("CandidateVotes")),
                vote_pct=vote_pct,
                is_winner=None,
                result_type="unofficial",
                office_title=office_title,
                is_write_in_aggregate=False,
                jurisdiction_fragment=area_num,
                raw={"contest_code": race_id, "party_code": party_code},
            )
        )

    return rows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest results/tests/test_nm_adapter.py --no-migrations -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add backend/results/adapters/nm_parse.py backend/results/tests/test_nm_adapter.py backend/results/tests/fixtures/nm_media_excerpt.csv
git commit -m "feat(nm): add BPro election-wide CSV parser with real captured fixture"
```

---

### Task 2: `NewMexicoAdapter` — fetch, checksum-cache, and wire into `StateResultsAdapter`

**Files:**
- Create: `backend/results/adapters/nm.py`
- Modify: `backend/results/tests/test_nm_adapter.py` (append this task's tests)

**Interfaces:**
- Consumes: `parse_election_wide_csv` (Task 1), `AdapterResult`/`ResultRow`/`StateResultsAdapter` (existing, `results/adapters/base.py`), `register`/`get_adapter` (existing, `results/adapters/registry.py`) — do not modify any of these.
- Produces: `NewMexicoAdapter` registered under state `"NM"` — consumed by `results.tasks.ingest_official_results` via `results.adapters.registry.get_adapter("NM")`. No new Celery task or endpoint is needed.

- [ ] **Step 1: Write the failing test**

Append to `backend/results/tests/test_nm_adapter.py`. Add these imports at the top of the file alongside the existing `import os`:

```python
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
```

Then append:

```python
from results.adapters.nm import NewMexicoAdapter, NmBproRetryableError


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
    assert len(result.rows) == 20
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest results/tests/test_nm_adapter.py --no-migrations -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'results.adapters.nm'`

- [ ] **Step 3: Write the implementation**

```python
# backend/results/adapters/nm.py
"""
New Mexico (NM) results adapter — BPro TotalVote Election Night Reporting.

Source: https://electionresults.sos.nm.gov/resultsCSV.aspx
Access: Public HTTPS. Cloudflare/bot-protection status is UNVERIFIED — a
        defensive browser User-Agent header is sent (Missouri's SOS needed
        one, Maryland's did not); confirm live when deploying.
Schema: election-wide CSV, one row per (race, candidate-or-ballot-choice),
        combined (non-precinct) vote totals for the whole election. See
        nm_parse.py for the parsing logic, including the office-title
        collision fix required for NM's hyper-local municipal races.

This is the BPro side only. New Mexico also runs Civera ElectionStats (a
separate, unrelated historical GraphQL database) — deliberately NOT built
here per docs/state-research/NM/NM-Election_ResearchV4.md's explicit
recommendation not to collapse the two systems into one adapter. Tracked
as follow-up work in GitHub issue #84.

Election ID (eid) resolution: hardcoded to eid=2897 (the 2025 Regular Local
Election) for this historical-snapshot POC. Live eid discovery for future
elections is out of scope — the research doc flags this as an open,
unresolved question.
"""
from __future__ import annotations

import hashlib
import logging

import requests
from django.core.cache import cache

from .base import AdapterResult, StateResultsAdapter
from .nm_parse import parse_election_wide_csv
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days
_ELECTION_WIDE_CSV_URL = (
    "https://electionresults.sos.nm.gov/resultsCSV.aspx?text=All&type=STATE&map=CTY&eid=2897"
)
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_EXPECTED_CSV_HEADER_PREFIX = b"RaceID,RaceName"


class NmBproError(Exception):
    """Non-retryable New Mexico BPro TotalVote integration error."""


class NmBproRetryableError(NmBproError):
    """Transient error that warrants a retry (network/non-CSV response)."""


@register
class NewMexicoAdapter(StateResultsAdapter):
    state = "NM"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"nm_bpro:checksum:{election_id}"

    def _fetch_csv_bytes(self, url: str) -> bytes:
        try:
            response = requests.get(url, headers={"User-Agent": _BROWSER_USER_AGENT}, timeout=30)
        except requests.RequestException as exc:
            raise NmBproRetryableError(f"NM BPro GET failed: {exc}") from exc

        if response.status_code != 200 or not response.content.startswith(_EXPECTED_CSV_HEADER_PREFIX):
            raise NmBproRetryableError(
                f"NM BPro did not return the expected CSV (status={response.status_code}) for url={url}"
            )

        return response.content

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("nm_bpro.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        try:
            csv_bytes = self._fetch_csv_bytes(_ELECTION_WIDE_CSV_URL)
        except NmBproRetryableError as exc:
            logger.warning("nm_bpro.adapter.csv_fetch_failed err=%s", exc)
            return AdapterResult(
                rows=[], source_url=_ELECTION_WIDE_CSV_URL, mapping_confidence="none",
                notes=f"Failed to fetch election-wide CSV for election {election_id}",
            )

        checksum = hashlib.md5(csv_bytes).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=_ELECTION_WIDE_CSV_URL, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        rows = parse_election_wide_csv(csv_bytes.decode("utf-8"))

        if not rows:
            return AdapterResult(
                rows=[], source_url=_ELECTION_WIDE_CSV_URL, mapping_confidence="none",
                notes=f"No result rows parsed for election {election_id}",
            )

        return AdapterResult(
            rows=rows,
            source_url=_ELECTION_WIDE_CSV_URL,
            mapping_confidence="full",
            source_version=checksum,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest results/tests/test_nm_adapter.py --no-migrations -v`
Expected: 12 passed (8 from Task 1 + 4 new)

- [ ] **Step 5: Commit**

```bash
git add backend/results/adapters/nm.py backend/results/tests/test_nm_adapter.py
git commit -m "feat(nm): add NewMexicoAdapter fetching and parsing BPro's election-wide CSV"
```

---

### Task 3: Register the adapter and verify the bootstrap path end-to-end

**Files:**
- Modify: `backend/results/apps.py`
- Modify: `backend/results/tests/test_nm_adapter.py` (append the bootstrap-path integration test)

**Interfaces:**
- Consumes: everything from Tasks 1–2, plus `results.tasks._bootstrap_races_from_results` (existing, read-only — do not modify `results/tasks.py`).
- Produces: `NewMexicoAdapter` discoverable via `results.adapters.registry.get_adapter("NM")` at Django startup.

This task's verification matters more here than it did for Maryland/Missouri's equivalent final task: `results.tasks.ingest_official_results` only calls `_process_race_results` against pre-existing `Race` rows and falls back to `_bootstrap_races_from_results` when `Race.objects.filter(election=election)` is empty. NM's hyper-local municipal races (mayors, school boards, water districts) are extremely unlikely to already exist via Google Civic API sync the way Maryland/Missouri's federal/statewide races plausibly do — so the bootstrap path is this adapter's *primary* real-world code path, not a rarely-hit fallback. Without directly testing it, Task 1/2's parsing rules (office-title qualification, contest_code tagging, MEASURE/CANDIDATE classification) would be verified only in the parser's in-memory output, never against real `Race`/`Candidate` creation.

Note on what disambiguates the two "Mayor" contests in this path specifically: `_bootstrap_races_from_results` groups rows by `(office_title, source_identity)`, and `source_identity` is derived from `row.raw["contest_code"]` (the BPro RaceID), which `nm_parse.py` sets distinctly on every row. So the two Mayor contests bootstrap as separate `Race`s by `contest_code` alone, independent of the office_title qualification. The office_title qualification's own defense-in-depth value is for a different path — `_process_race_results`'s fallback title-matching against *pre-existing* races lacking `contest_code` metadata — which this bootstrap test does not exercise (see "Follow-up work" below).

- [ ] **Step 1: Register the adapter module**

In `backend/results/apps.py`, find this line inside `ResultsConfig.ready()`'s `adapter_modules` list:

```python
            "ms", "mt", "nc", "nd", "ne", "nh", "nj", "nv", "ny", "oh",
```

Replace with (inserting `"nm"` alphabetically between `"nj"` and `"nv"`):

```python
            "ms", "mt", "nc", "nd", "ne", "nh", "nj", "nm", "nv", "ny", "oh",
```

- [ ] **Step 2: Write the failing bootstrap-path test**

Append to `backend/results/tests/test_nm_adapter.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest results/tests/test_nm_adapter.py::test_bootstrap_creates_separate_races_for_colliding_office_titles --no-migrations -v`
Expected: FAIL — `results.adapters.registry.get_adapter("NM")` / the module isn't registered yet, or (if the module import alone is enough for `@register` to have fired in-process) the test should otherwise pass once Task 1/2's code exists; if it unexpectedly passes before Step 1's `apps.py` edit, that's fine — this specific test doesn't depend on registry wiring, only on `nm_parse`/`tasks` being importable. Treat "already passing" as acceptable here, not a signal to skip Step 1 (the registry edit is still required for the adapter to be reachable via `get_adapter("NM")` in production).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest results/tests/test_nm_adapter.py --no-migrations -v`
Expected: 13 passed (12 from Tasks 1–2 + 1 new)

- [ ] **Step 5: Verify the adapter is discoverable via the registry**

Run:
```bash
cd backend && SECRET_KEY=test-only python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()
from results.adapters.registry import list_supported_states
assert 'NM' in list_supported_states(), list_supported_states()
print('OK: NM registered')
"
```
Expected: `OK: NM registered`

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `cd backend && pytest --no-migrations -q`
Expected: all tests pass, no regressions in other adapters' tests.

- [ ] **Step 7: Run ruff and Django's system check**

Run: `cd backend && ruff check . && python manage.py check`
Expected: `All checks passed!` and `System check identified no issues (0 silenced).`

- [ ] **Step 8: Commit**

```bash
git add backend/results/apps.py backend/results/tests/test_nm_adapter.py
git commit -m "feat(nm): register NewMexicoAdapter and verify the bootstrap-races path"
```

---

## Follow-up work (explicitly out of scope for this plan)

- **Untested `_process_race_results` fallback title-matching against pre-existing races** — `results/tasks.py`'s fallback path (around `_office_title_key(r.office_title) == _office_title_key(race.office_title)`, tasks.py:264-273), which matches results against *pre-existing* `Race` rows lacking `contest_code` metadata, is not covered by any NM test. The office_title qualification from Task 1 is the real defense-in-depth mechanism for that path. Accepted as a deferred gap for now since no other NM race-creation adapter exists yet that would populate such pre-existing races; revisit if/when one does.
- **Civera ElectionStats** — the entire historical GraphQL-backed system. Separate vendor, separate API, unrelated ID space. Tracked in GitHub issue #84; see `NM-Election_ResearchV4.md` Part III/V/VI for full findings and the recommended `CiveraElectionStatsAdapter` phase breakdown (C1–C5) when picked up.
- **BPro precinct/county JSON drill-down** (`GetMapData`/`GetMapDataArchive`) — needs an HTML category-page scraping step to discover `raceid`/`officeseqno`/`countyid`; no clean metadata endpoint exists for that. Would unlock precinct-level results and the `Winner` field this build doesn't have access to.
- **Live `eid` discovery** for the current/future election cycle — this plan hardcodes `eid=2897`. The research doc explicitly flags "how are `eid` values best discovered programmatically?" as unresolved.
- **Turnout/reporting-status endpoints** (`GetVoterTurnoutArchive`/`GetVoterTurnoutData`, `resultsCountyLastUpdated.aspx`).
- **The 5 ballot-measure titles that miss `results/tasks.py`'s `_MEASURE_TITLE_KEYWORDS`** (e.g. `"LORDSBURG ACT LOCAL OPTION GROSS RECEIPTS TAX: ..."`, `"MAYOR VOTING RIGHTS: Should the Santa Fe Municipal Charter..."`) — verified via direct check against all 118 real ballot-measure titles in `Media.csv`; these 5 (0.8%) would bootstrap as `CANDIDATE` races with zero candidates, since this adapter correctly routes their rows to `option_label` regardless of the title-keyword miss. Small enough to accept and document for this POC rather than block on — could be fixed generically in a follow-up touching shared `results/tasks.py` logic (e.g. "any race whose rows are 100% `option_label`-routed is a measure, regardless of title keywords") rather than this NM-specific plan.
- **Verifying Cloudflare/bot-protection status live** — flagged in Global Constraints as the first thing to confirm when implementing Task 2, not assumed either way in this plan.
- **The privacy-masking-bypass finding** (research doc Section 22) — independent of this plan's scope; tracked in issue #84.

## Post-merge CI fix: `office_title` length truncation

CI (running against real PostgreSQL) caught a bug the local SQLite-backed test runs could not: `Race.office_title` is a `CharField(max_length=255)`, and 108 of the 599 real races in the full captured election (`Media.csv`) have a `RaceName` exceeding that — full ballot-measure legal question text, up to 636 characters observed — since PostgreSQL enforces `VARCHAR` length strictly and SQLite does not. Fixed in `nm_parse.py` by truncating `office_title` to 255 chars (with a trailing `…` marker) after qualification. This cannot reintroduce the office-title collision risk described above: `contest_code`-based `source_identity`, not the `office_title` string, is what actually disambiguates races on the bootstrap path, and every row always carries a real, distinct `contest_code` regardless of truncation. The fixture and its dependent tests (`nm_media_excerpt.csv`, row-count assertions) were updated to include a real long-title example (`RaceID=1304`, the Tatum bond question) and a dedicated truncation test.

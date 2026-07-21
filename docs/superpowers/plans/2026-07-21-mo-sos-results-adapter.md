# Missouri (MO) SOS Certified Results Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship MO's Stage 2 (certified results) adapter for statewide offices, parsing the Missouri SOS's text-based "Grand Totals" PDF, validated entirely against the historical Nov 5, 2024 general election, so MO reaches "Results Coverage Only" tier (same tier as NC/NY/CA/MD) with races sourced from the Google Civic API.

**Architecture:** Missouri has no results API and is not on Clarity — results are published as a single statewide "Grand Totals" PDF (`https://www.sos.mo.gov/CMSImages/ElectionResultsStatistics/{filename}.pdf`), a text-based (not scanned) report with one repeated block per contest: an `"{Office} ({N} of {M} Precincts Reported)"` header line, one line per candidate (`"{Name} {Party} {Votes} {Pct}%"`), and a `"Total Votes {N}"` trailer. This mirrors the existing Maine adapter's architecture exactly (`results/adapters/me.py`) — no separate `integrations.mo_sos` Django app is needed, since (like Maine) there's no Stage 1/model code, just an HTTP fetch + `pdfplumber` text extraction + regex parsing, all self-contained in `results/adapters/`. A new `results/adapters/mo.py` `StateResultsAdapter` fetches the PDF, extracts text via `pdfplumber`, and delegates to `results/adapters/mo_parse.py` (pure parsing functions, testable without any HTTP or PDF library dependency in the parser tests) to emit `ResultRow`s.

**Tech Stack:** Django, `requests`, `pdfplumber` (already a project dependency — used by `results/adapters/me.py`), Python's stdlib `re` module.

## Global Constraints

- **Statewide top-of-ticket offices only, this build:** `U.S. President and Vice President`, `U.S. Senator`, `Governor`, `Lieutenant Governor` — the four statewide candidate contests confirmed present (and appearing first, on PDF page 1) in the Nov 5, 2024 general election Grand Totals PDF. U.S. House/State Senate/State House (district-level), judicial retention (`Yes Votes`/`No Votes` rows keyed by judge name), and constitutional amendments/ballot measures (`Yes Votes`/`No Votes` rows keyed by measure name) are explicitly out of scope for this plan — see "Follow-up work" below. The research doc explicitly warns judicial-retention and ballot-measure contests share the same `Yes Votes`/`No Votes` row shape and must be classified from context, not assumed — this build sidesteps that entirely by only looking for offices in the candidate-contest allowlist.
- **Historical POC only:** validate against the Nov 5, 2024 general election Grand Totals PDF at `https://www.sos.mo.gov/CMSImages/ElectionResultsStatistics/2024GeneralElection.pdf` (SHA-256 `fd3e58901873bde13552b06c2a48b1e47e94f9da6529d174a3e2fb51cccb7ebf`, 1,147,948 bytes, 36 pages — independently re-fetched and re-hashed 2026-07-21, matches the research doc's provenance table exactly). Live discovery of the current cycle's PDF URL/filename for future elections is out of scope — see "Follow-up work" below.
- **A realistic browser `User-Agent` header is required on every request to `sos.mo.gov`.** Confirmed by direct testing 2026-07-21: `requests.get(url)` with no headers returns `403` with a small Cloudflare "Just a moment..." challenge-page body (4,548 bytes); the identical request with `User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36` returns `200` with the real 1,147,948-byte PDF. This is a static-header requirement only — no CF-solver/JS-challenge infrastructure (like the one built for `oh_sos`) is needed for this endpoint.
- **PDF fetches must be validated by content, not just status code** — check the response starts with the `%PDF` magic bytes (confirmed present: `2550 4446 2d31 2e34` = `%PDF-1.4`) before attempting to parse it as a PDF, consistent with this research doc's repeated warning that MO SOS returns HTTP 200 with non-content bodies for broken URLs (e.g. the confirmed soft-404 at `/elections/resultsandstats`).
- **All fixture text in this plan is real, extracted data** — captured 2026-07-21 by downloading the actual 2024 Grand Totals PDF (re-verified against the research doc's SHA-256) and running `pdfplumber.open(...).pages[0].extract_text()` on it directly. No synthetic/invented data.
- No live network calls in the test suite itself — all HTTP is mocked using the captured fixture text.
- Run tests with `pytest --no-migrations` (local test-DB creation breaks on an unrelated bad migration in this environment).
- Full research context: `docs/state-research/MO/MO-Election_Research_UpdatedV2.md`.

---

### Task 1: `mo_parse.py` — parse Grand Totals PDF text into `ResultRow`s

**Files:**
- Create: `backend/results/adapters/mo_parse.py`
- Create: `backend/results/tests/fixtures/mo_grand_totals_page1_excerpt.txt` (real extracted text — content given below)
- Test: `backend/results/tests/test_mo_adapter.py` (this task's tests only — Task 2 adds more to the same file)

**Interfaces:**
- Produces: `parse_grand_totals_text(text: str, office_allowlist: frozenset[str]) -> list[ResultRow]`. Consumed by Task 2's `MissouriAdapter.fetch_results`. Uses the existing `ResultRow` dataclass from `results/adapters/base.py` — do not modify that file, just import from it.

The fixture file below is real text extracted 2026-07-21 via `pdfplumber.open("2024GeneralElection.pdf").pages[0].extract_text()`, from the exact PDF whose SHA-256 (`fd3e58901873bde13552b06c2a48b1e47e94f9da6529d174a3e2fb51cccb7ebf`) matches the research doc's provenance table. Its content (create this file with **exactly** this content, including blank-line-free formatting):

```text
U.S. President and Vice President (3573 of 3573 Precincts Reported)
Donald J. Trump, JD Vance Republican 1,751,986 58.5%
Kamala D. Harris, Tim Walz Democratic 1,200,599 40.1%
Chase Oliver, Mike ter Maat Libertarian 23,876 0.8%
Jill Stein, Rudolph Ware Green 17,135 0.6%
Peter Sonski, Lauren Onak Write-in 1,069 0.0%
Claudia De la Cruz, Karina Garcia Write-in 618 0.0%
Shiva Ayyadurai, Crystal Ellis Write-in 34 0.0%
Future Madam Potus, Jessica Kennedy Write-in 10 0.0%
Total Votes 2,995,327
U.S. Senator (3572 of 3572 Precincts Reported)
Josh Hawley Republican 1,651,907 55.6%
Lucas Kunce Democratic 1,243,728 41.8%
W. C. Young Libertarian 35,671 1.2%
Jared Young Better 21,111 0.7%
Nathan Kline Green 20,123 0.7%
Gina Bufe Write-in 19 0.0%
Total Votes 2,972,559
Governor (3572 of 3572 Precincts Reported)
Mike Kehoe Republican 1,750,802 59.1%
Crystal Quade Democratic 1,146,173 38.7%
Bill Slantz Libertarian 40,908 1.4%
Paul Lehmann Green 22,359 0.8%
Theo (Ted) Brown Sr Write-in 24 0.0%
Total Votes 2,960,266
Lieutenant Governor (3572 of 3572 Precincts Reported)
Dave Wasinger Republican 1,671,771 57.4%
Richard Brown Democratic 1,121,608 38.5%
Ken Iverson Libertarian 61,731 2.1%
Danielle (Dani) Elliott Green 58,260 2.0%
Total Votes 2,913,370
```

Note the parsing subtleties this exact real data exercises: candidate names containing commas (`"Donald J. Trump, JD Vance"`, running-mate pairs), periods and initials (`"W. C. Young"`), parentheticals (`"Theo (Ted) Brown Sr"`, `"Danielle (Dani) Elliott"`), and multiple distinct `Write-in` rows within a single contest (not one aggregate — MO's Grand Totals report lists each write-in filer individually with their own vote count, unlike a single collapsed "Write-In" bucket).

- [ ] **Step 1: Save the fixture file**

```bash
mkdir -p backend/results/tests/fixtures
cat > backend/results/tests/fixtures/mo_grand_totals_page1_excerpt.txt << 'EOF'
U.S. President and Vice President (3573 of 3573 Precincts Reported)
Donald J. Trump, JD Vance Republican 1,751,986 58.5%
Kamala D. Harris, Tim Walz Democratic 1,200,599 40.1%
Chase Oliver, Mike ter Maat Libertarian 23,876 0.8%
Jill Stein, Rudolph Ware Green 17,135 0.6%
Peter Sonski, Lauren Onak Write-in 1,069 0.0%
Claudia De la Cruz, Karina Garcia Write-in 618 0.0%
Shiva Ayyadurai, Crystal Ellis Write-in 34 0.0%
Future Madam Potus, Jessica Kennedy Write-in 10 0.0%
Total Votes 2,995,327
U.S. Senator (3572 of 3572 Precincts Reported)
Josh Hawley Republican 1,651,907 55.6%
Lucas Kunce Democratic 1,243,728 41.8%
W. C. Young Libertarian 35,671 1.2%
Jared Young Better 21,111 0.7%
Nathan Kline Green 20,123 0.7%
Gina Bufe Write-in 19 0.0%
Total Votes 2,972,559
Governor (3572 of 3572 Precincts Reported)
Mike Kehoe Republican 1,750,802 59.1%
Crystal Quade Democratic 1,146,173 38.7%
Bill Slantz Libertarian 40,908 1.4%
Paul Lehmann Green 22,359 0.8%
Theo (Ted) Brown Sr Write-in 24 0.0%
Total Votes 2,960,266
Lieutenant Governor (3572 of 3572 Precincts Reported)
Dave Wasinger Republican 1,671,771 57.4%
Richard Brown Democratic 1,121,608 38.5%
Ken Iverson Libertarian 61,731 2.1%
Danielle (Dani) Elliott Green 58,260 2.0%
Total Votes 2,913,370
EOF
```

- [ ] **Step 2: Write the failing test**

```python
# backend/results/tests/test_mo_adapter.py
import os

from results.adapters.mo_parse import parse_grand_totals_text

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture(name: str) -> str:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


_STATEWIDE_OFFICES = frozenset({
    "U.S. President and Vice President", "U.S. Senator", "Governor", "Lieutenant Governor",
})


def test_parse_grand_totals_text_extracts_all_candidate_rows_for_allowlisted_offices():
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=_STATEWIDE_OFFICES)

    # 8 (President) + 6 (Senator) + 5 (Governor) + 4 (Lt. Governor) = 23
    assert len(rows) == 23
    by_office = {}
    for row in rows:
        by_office.setdefault(row.office_title, []).append(row)
    assert len(by_office["U.S. President and Vice President"]) == 8
    assert len(by_office["U.S. Senator"]) == 6
    assert len(by_office["Governor"]) == 5
    assert len(by_office["Lieutenant Governor"]) == 4


def test_parse_grand_totals_text_handles_names_with_commas_and_parens():
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=_STATEWIDE_OFFICES)
    by_name = {r.candidate_name: r for r in rows}

    trump = by_name["Donald J. Trump, JD Vance"]
    assert trump.vote_count == 1751986
    assert trump.raw["party"] == "Republican"
    assert trump.office_title == "U.S. President and Vice President"

    brown = by_name["Theo (Ted) Brown Sr"]
    assert brown.vote_count == 24
    assert brown.raw["party"] == "Write-in"


def test_parse_grand_totals_text_keeps_multiple_write_in_rows_distinct():
    """MO's Grand Totals report lists each write-in filer individually with
    their own vote count — unlike MD's adapter, there is no single collapsed
    'Write-In' aggregate row to worry about here."""
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=_STATEWIDE_OFFICES)
    president_write_ins = [
        r for r in rows
        if r.office_title == "U.S. President and Vice President" and r.raw["party"] == "Write-in"
    ]
    assert len(president_write_ins) == 4
    names = {r.candidate_name for r in president_write_ins}
    assert names == {
        "Peter Sonski, Lauren Onak", "Claudia De la Cruz, Karina Garcia",
        "Shiva Ayyadurai, Crystal Ellis", "Future Madam Potus, Jessica Kennedy",
    }
    assert all(r.is_write_in_aggregate is False for r in president_write_ins)


def test_parse_grand_totals_text_sets_result_type_and_vote_pct():
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=_STATEWIDE_OFFICES)
    hawley = next(r for r in rows if r.candidate_name == "Josh Hawley")
    assert hawley.result_type == "official"
    assert hawley.vote_pct == 55.6


def test_parse_grand_totals_text_excludes_offices_not_in_allowlist():
    text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    rows = parse_grand_totals_text(text, office_allowlist=frozenset({"Attorney General"}))
    assert rows == []


def test_parse_grand_totals_text_ignores_total_votes_lines():
    text = "Governor (1 of 1 Precincts Reported)\nJane Doe Republican 100 100.0%\nTotal Votes 100\n"
    rows = parse_grand_totals_text(text, office_allowlist=frozenset({"Governor"}))
    assert len(rows) == 1
    assert rows[0].candidate_name == "Jane Doe"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest results/tests/test_mo_adapter.py --no-migrations -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'results.adapters.mo_parse'`

- [ ] **Step 4: Write the implementation**

```python
# backend/results/adapters/mo_parse.py
"""
Parser for Missouri SOS's "Grand Totals" certified-results PDF text.

MO has no results API and is not on Clarity — results are published as a
text-based PDF (confirmed not a scanned image; pdfplumber extracts real
text). The report is a flat, repeated-block structure per contest:

    {Office} ({N} of {M} Precincts Reported)
    {Candidate Name} {Party} {Votes} {Pct}%
    ...
    Total Votes {N}

Unlike MD, MO's Grand Totals report lists each write-in filer individually
by name with their own vote count — there is no single collapsed
"Write-In" aggregate row, so no write-in-specific aggregation is needed
here (each row already has result_type="official", is_write_in_aggregate
always False).

Judicial-retention and ballot-measure contests share a different row shape
("{Candidate/Measure} Yes Votes {N} {Pct}%" / "No {Votes} {N} {Pct}%") and
are NOT handled by this parser — they are filtered out entirely by the
office_allowlist, since this build only recognizes statewide candidate
contest office names.
"""
from __future__ import annotations

import re

from .base import ResultRow

_HEADER_RE = re.compile(r'^(?P<office>.+?)\s+\((?P<reported>\d+) of (?P<total>\d+) Precincts Reported\)$')
_CANDIDATE_RE = re.compile(r'^(?P<name>.+?)\s+(?P<party>[A-Za-z][A-Za-z\-]*)\s+(?P<votes>[\d,]+)\s+(?P<pct>[\d.]+)%$')
_TOTAL_RE = re.compile(r'^Total Votes [\d,]+$')


def parse_grand_totals_text(text: str, office_allowlist: frozenset[str]) -> list[ResultRow]:
    rows: list[ResultRow] = []
    current_office: str | None = None
    in_scope = False

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        header_match = _HEADER_RE.match(line)
        if header_match:
            current_office = header_match.group("office")
            in_scope = current_office in office_allowlist
            continue

        if not in_scope:
            continue

        if _TOTAL_RE.match(line):
            continue

        candidate_match = _CANDIDATE_RE.match(line)
        if not candidate_match:
            continue

        vote_count = int(candidate_match.group("votes").replace(",", ""))
        rows.append(
            ResultRow(
                candidate_name=candidate_match.group("name"),
                option_label=None,
                vote_count=vote_count,
                vote_pct=float(candidate_match.group("pct")),
                is_winner=None,
                result_type="official",
                office_title=current_office,
                is_write_in_aggregate=False,
                raw={"party": candidate_match.group("party")},
            )
        )

    return rows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest results/tests/test_mo_adapter.py --no-migrations -v`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add backend/results/adapters/mo_parse.py backend/results/tests/test_mo_adapter.py backend/results/tests/fixtures/mo_grand_totals_page1_excerpt.txt
git commit -m "feat(mo): add Grand Totals PDF text parser with real captured fixture"
```

---

### Task 2: `MissouriAdapter` — fetch, extract, and wire into `StateResultsAdapter`

**Files:**
- Create: `backend/results/adapters/mo.py`
- Modify: `backend/results/tests/test_mo_adapter.py` (append this task's tests)

**Interfaces:**
- Consumes: `parse_grand_totals_text` (Task 1), `AdapterResult`/`ResultRow`/`StateResultsAdapter` (existing, `results/adapters/base.py`), `register`/`get_adapter` (existing, `results/adapters/registry.py`) — do not modify any of these.
- Produces: `MissouriAdapter` registered under state `"MO"` — consumed by `results.tasks.ingest_official_results` via `results.adapters.registry.get_adapter("MO")`. No new Celery task or endpoint is needed — Stage-2-only adapters are picked up automatically via the registry, exactly as established for MD/NC/CA/NY.

- [ ] **Step 1: Write the failing test**

Append to `backend/results/tests/test_mo_adapter.py`:

```python
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.mo import MissouriAdapter, MoSosRetryableError


@patch("results.adapters.mo.requests.get")
def test_fetch_grand_totals_pdf_sends_browser_user_agent(mock_get):
    response = MagicMock(status_code=200, content=b"%PDF-1.4\n...")
    mock_get.return_value = response

    result = MissouriAdapter()._fetch_grand_totals_pdf_bytes("https://www.sos.mo.gov/example.pdf")

    assert result == b"%PDF-1.4\n..."
    called_headers = mock_get.call_args.kwargs["headers"]
    assert "Mozilla" in called_headers["User-Agent"]


@patch("results.adapters.mo.requests.get")
def test_fetch_grand_totals_pdf_rejects_non_pdf_content(mock_get):
    """MO SOS returns HTTP 200 with a Cloudflare challenge-page body when the
    request lacks a browser User-Agent — must be detected by content
    (missing %PDF magic bytes), never trusted by status code alone."""
    response = MagicMock(status_code=200, content=b"<!DOCTYPE html><html>Just a moment...</html>")
    mock_get.return_value = response

    with pytest.raises(MoSosRetryableError):
        MissouriAdapter()._fetch_grand_totals_pdf_bytes("https://www.sos.mo.gov/example.pdf")


@pytest.mark.django_db
@patch("results.adapters.mo.MissouriAdapter._fetch_grand_totals_pdf_bytes")
@patch("results.adapters.mo.pdfplumber")
def test_fetch_results_extracts_text_and_parses_statewide_offices(mock_pdfplumber, mock_fetch):
    election = Election.objects.create(
        name="2024 Missouri General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MO",
        source_id="mo-2024-general",
        status=Election.Status.RESULTS_CERTIFIED,
    )
    mock_fetch.return_value = b"%PDF-1.4\n..."

    fixture_text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fixture_text
    mock_pdf_context = MagicMock()
    mock_pdf_context.__enter__.return_value.pages = [mock_page]
    mock_pdfplumber.open.return_value = mock_pdf_context

    result = MissouriAdapter().fetch_results(election_date=election.election_date, election_id=election.pk)

    assert result.mapping_confidence == "full"
    assert len(result.rows) == 23
    offices = {r.office_title for r in result.rows}
    assert offices == {"U.S. President and Vice President", "U.S. Senator", "Governor", "Lieutenant Governor"}


@pytest.mark.django_db
@patch("results.adapters.mo.MissouriAdapter._fetch_grand_totals_pdf_bytes")
@patch("results.adapters.mo.pdfplumber")
def test_fetch_results_returns_unchanged_when_checksum_matches_cache(mock_pdfplumber, mock_fetch):
    from django.core.cache import cache

    election = Election.objects.create(
        name="2024 Missouri General Election",
        election_date=date(2024, 11, 5),
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        state="MO",
        source_id="mo-2024-general-2",
        status=Election.Status.RESULTS_CERTIFIED,
    )
    mock_fetch.return_value = b"%PDF-1.4\n..."
    fixture_text = _load_fixture("mo_grand_totals_page1_excerpt.txt")
    mock_page = MagicMock()
    mock_page.extract_text.return_value = fixture_text
    mock_pdf_context = MagicMock()
    mock_pdf_context.__enter__.return_value.pages = [mock_page]
    mock_pdfplumber.open.return_value = mock_pdf_context

    adapter = MissouriAdapter()
    first = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    cache.set(adapter.version_cache_key(election.pk), first.source_version)

    second = adapter.fetch_results(election_date=election.election_date, election_id=election.pk)
    assert second.unchanged is True
    assert second.rows == []


@pytest.mark.django_db
def test_fetch_results_returns_empty_for_missing_election():
    result = MissouriAdapter().fetch_results(election_date=date(2024, 11, 5), election_id=999999)
    assert result.rows == []
    assert result.mapping_confidence == "none"
```

Add the missing top-of-file imports this appended block needs — `Election` is not yet imported in this test file (Task 1 didn't need it). Add near the top of `backend/results/tests/test_mo_adapter.py`, alongside the existing `import os`:

```python
from elections.models import Election
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest results/tests/test_mo_adapter.py --no-migrations -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'results.adapters.mo'`

- [ ] **Step 3: Write the implementation**

```python
# backend/results/adapters/mo.py
"""
Missouri (MO) results adapter — Missouri Secretary of State.

Source: https://www.sos.mo.gov/CMSImages/ElectionResultsStatistics/{filename}.pdf
Access: Public HTTPS. Cloudflare-fronted — a realistic browser User-Agent
        header is REQUIRED (confirmed via direct testing 2026-07-21; see
        docs/state-research/MO/MO-Election_Research_UpdatedV2.md), otherwise
        the request gets a 403 Cloudflare challenge page instead of the PDF.
Schema: text-based (not scanned) PDF, "Grand Totals" report — one repeated
        block per contest. See mo_parse.py for the parsing logic.

Scope (this build): statewide top-of-ticket offices on the historical
Nov 5, 2024 general election only — "U.S. President and Vice President",
"U.S. Senator", "Governor", "Lieutenant Governor". District-level races,
judicial retention, and ballot measures/constitutional amendments are
follow-up work (need contest-type classification the current build
sidesteps — see the plan's "Follow-up work" section).

Cycle URL resolution: hardcoded to the 2024 general election's known PDF
URL for this historical POC. Live discovery of the current cycle's PDF
URL/filename for future elections is out of scope — see the plan's
"Follow-up work" section.
"""
from __future__ import annotations

import hashlib
import io
import logging

import pdfplumber
import requests
from django.core.cache import cache

from .base import AdapterResult, StateResultsAdapter
from .mo_parse import parse_grand_totals_text
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days
_OFFICE_ALLOWLIST = frozenset({
    "U.S. President and Vice President", "U.S. Senator", "Governor", "Lieutenant Governor",
})
_GRAND_TOTALS_URL = "https://www.sos.mo.gov/CMSImages/ElectionResultsStatistics/2024GeneralElection.pdf"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_PDF_MAGIC_BYTES = b"%PDF"


class MoSosError(Exception):
    """Non-retryable Missouri SOS integration error."""


class MoSosRetryableError(MoSosError):
    """Transient error that warrants a retry (network/CF-challenge/non-PDF response)."""


@register
class MissouriAdapter(StateResultsAdapter):
    state = "MO"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"mo_sos:checksum:{election_id}"

    def _fetch_grand_totals_pdf_bytes(self, url: str) -> bytes:
        try:
            response = requests.get(url, headers={"User-Agent": _BROWSER_USER_AGENT}, timeout=30)
        except requests.RequestException as exc:
            raise MoSosRetryableError(f"MO SOS GET failed: {exc}") from exc

        if response.status_code != 200 or not response.content.startswith(_PDF_MAGIC_BYTES):
            raise MoSosRetryableError(
                f"MO SOS did not return a PDF (status={response.status_code}) for url={url}"
            )

        return response.content

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("mo_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        try:
            pdf_bytes = self._fetch_grand_totals_pdf_bytes(_GRAND_TOTALS_URL)
        except MoSosRetryableError as exc:
            logger.warning("mo_sos.adapter.pdf_fetch_failed err=%s", exc)
            return AdapterResult(
                rows=[], source_url=_GRAND_TOTALS_URL, mapping_confidence="none",
                notes=f"Failed to fetch Grand Totals PDF for election {election_id}",
            )

        checksum = hashlib.md5(pdf_bytes).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=_GRAND_TOTALS_URL, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        rows = parse_grand_totals_text(text, office_allowlist=_OFFICE_ALLOWLIST)

        if not rows:
            return AdapterResult(
                rows=[], source_url=_GRAND_TOTALS_URL, mapping_confidence="none",
                notes=f"No statewide contest rows parsed for election {election_id}",
            )

        return AdapterResult(
            rows=rows,
            source_url=_GRAND_TOTALS_URL,
            mapping_confidence="full",
            source_version=checksum,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest results/tests/test_mo_adapter.py --no-migrations -v`
Expected: 11 passed (6 from Task 1 + 5 new)

- [ ] **Step 5: Commit**

```bash
git add backend/results/adapters/mo.py backend/results/tests/test_mo_adapter.py
git commit -m "feat(mo): add MissouriAdapter fetching and parsing the Grand Totals PDF"
```

---

### Task 3: Register the adapter and verify end-to-end

**Files:**
- Modify: `backend/results/apps.py`

**Interfaces:**
- Consumes: everything from Tasks 1–2.
- Produces: `MissouriAdapter` discoverable via `results.adapters.registry.get_adapter("MO")` at Django startup.

- [ ] **Step 1: Register the adapter module**

In `backend/results/apps.py`, find this line inside `ResultsConfig.ready()`'s `adapter_modules` list:

```python
            "id", "ia", "il", "in", "ks", "ky", "la", "ma", "md", "me", "mi", "mn",
```

Replace with (inserting `"mo"` alphabetically after `"mn"`):

```python
            "id", "ia", "il", "in", "ks", "ky", "la", "ma", "md", "me", "mi", "mn", "mo",
```

- [ ] **Step 2: Verify the adapter is discoverable via the registry**

Run:
```bash
cd backend && SECRET_KEY=test-only python -c "
import django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
django.setup()
from results.adapters.registry import list_supported_states
assert 'MO' in list_supported_states(), list_supported_states()
print('OK: MO registered')
"
```
Expected: `OK: MO registered`

- [ ] **Step 3: Run the full test suite to check for regressions**

Run: `cd backend && pytest --no-migrations -q`
Expected: all tests pass, no regressions in other adapters' tests.

- [ ] **Step 4: Run Django's system check**

Run: `cd backend && python manage.py check`
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 5: Commit**

```bash
git add backend/results/apps.py
git commit -m "feat(mo): register MissouriAdapter in results app startup"
```

---

## Follow-up work (explicitly out of scope for this plan)

- **U.S. House / State Senate / State House (district-level results):** same Grand Totals PDF contains these contests further down each page; just needs the office allowlist expanded and confirmation the same parsing regex handles district-numbered office titles (e.g. `"State Senator - District 5"`) without collision.
- **Judicial retention and ballot measures (Constitutional Amendments):** both use a `"{Name} Yes Votes {N} {Pct}%"` / `"No Votes {N} {Pct}%"` row shape that this build's parser does not attempt to handle — the research doc explicitly warns these two contest types are visually identical and must be classified from context (a measure vs. a judge's name) rather than assumed. Separate plan.
- **County/election-jurisdiction-level results:** the separate 153-page "Results by County" PDF (`ActualResults-November52024.pdf`, SHA-256 `0ddbfb6f895e25cddb0769f1a179e8e4d9085fdc844b670576fe5060e5f2fc69` — independently re-fetched and re-verified 2026-07-21) uses wide, layout-dependent tables spanning Missouri's 114 counties plus Kansas City and St. Louis City as separate rows (116 jurisdictions total) — needs coordinate/layout-aware PDF table extraction, not the line-based text parsing used here. Separate plan, higher effort per the research doc.
- **Current-cycle PDF discovery:** this plan hardcodes the 2024 general election's Grand Totals PDF URL. A production adapter needs to discover the current cycle's PDF filename from the results index page (`https://www.sos.mo.gov/elections/results`) rather than guessing a filename pattern — the research doc notes MO's PDF filenames are inconsistent across years/election types.
- **Stage 1 (candidate/race creation):** MO currently relies on the Google Civic API for race/election discovery (this plan's scope). A native adapter built on the candidate-filing portal (`s1.sos.mo.gov/candidatesonweb/`) would add richer data (filing dates, ballot-placement numbers, withdrawn-candidate reconciliation) — separate plan. Note the portal's `OfficeCode` values are opaque and cycle-specific (some compact like `SW35`, some space-delimited like `25 CN 1`) and must be discovered from the office index, never constructed by rule.
- **Certified ballot measures (Stage 1):** `https://www.sos.mo.gov/petitions/2026BallotMeasures` (note: `/elections/2026BallotMeasures` is a confirmed soft-404 — HTTP 200 with a "Page not found" body) has official ballot titles, fair-ballot language, and source legislation for certified measures. Separate plan.
- **Election calendar (Stage 1):** `https://www.sos.mo.gov/elections/calendar/2026cal` (confirmed on the `www` host, not `s1`) is a server-rendered HTML table of official election dates and filing/certification deadlines. Separate plan.
- **Stage 2 live/election-night results:** `https://enr.sos.mo.gov/` currently just 307-redirects to the static results page (no active reporting observed off-season). Per this repo's established convention (see TN/MD's live-dashboard deferrals), defer until the August 4, 2026 Missouri primary is actively reporting, so behavior can be captured and validated with a live HAR rather than guessed.

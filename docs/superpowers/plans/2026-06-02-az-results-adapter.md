# Arizona Results Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a results adapter for Arizona that fetches `Results.Summary.xml` from the AZ SOS HTTPS feed and maps statewide vote totals to `ResultRow` objects for both candidate races and ballot questions.

**Architecture:** A single self-contained adapter in `results/adapters/az.py` following the AR/CT pattern. XML is fetched via `requests` over **HTTPS** (`https://apps.azsos.gov/ftp/...` — confirmed HTTP 200). `fileId` from the XML header is used for change detection (increments each publish, more reliable than `resultsTimestamp`). The URL election name segment is derived from `election.election_type` with a `source_metadata['az_election_name']` override for non-standard elections. **`normalize_contest_name` from `integrations.az_sos.mappers` is called on every `contestLongName` before storing it as `office_title`** so that Stage 2 result rows can be matched to Stage 1 Race records by the task runner's string-equality join.

**Tech Stack:** `requests` + `xml.etree.ElementTree`; Django cache for version state; `@register` decorator for autodiscovery.

> **⚠️ Corrections applied (updated 2026-06-03):**
> - Election date is **2026-07-21** (not July 28 — changed by AZ HB2022 signed 2026-02-06)
> - Use **HTTPS** `https://apps.azsos.gov/ftp/...` — NOT FTP
> - Use **`fileId`** for change detection — NOT `resultsTimestamp`
> - `requests.get()` replaces `urllib.request.urlopen()`
> - **`normalize_contest_name` must be applied to `contestLongName`** — `_process_race_results` matches by string equality; without normalization every federal/state-legislative race silently gets PARTIAL_RESULTS with zero results written

---

## Key Reference Facts

**FTP URL pattern:**
```
ftp://ftp.azsos.gov/ElectionResults/{year}/State/{election_name}/Results.Summary.xml
```
Examples: `2024 Primary Election`, `2024 General Election`, `2024 Presidential Preference Election`

**XML schema (confirmed against 2024 Primary + General):**
```xml
<electionResult>
  <electionInformation>
    <resultsTimestamp>2024-08-14T14:58:31.307</resultsTimestamp>  <!-- version key -->
    <electionName>2024 Primary Election</electionName>
    <electionDate>2024-07-30</electionDate>
    <fileId>11261</fileId>
  </electionInformation>
  <contests>
    <!-- Candidate race: isQuestion="false" -->
    <contest key="13190" contestLongName="U.S. Senator (DEM)"
             isQuestion="false" precinctsReportingPercent="100.00" ...>
      <choices>
        <choice key="25634" choiceName="Gallego, Ruben" party="DEM"
                totalVotes="498927" isWriteIn="false" />
        <!-- totalVotes IS the statewide total — no need to sum county jurisdictions -->
      </choices>
    </contest>
    <!-- Ballot question: isQuestion="true", no key/party on choices -->
    <contest key="15510"
             contestLongName="Shall Bolick, Clint, Justice of the Arizona Supreme Court be retained?"
             isQuestion="true" ...>
      <choices>
        <choice choiceName="Yes" totalVotes="1534635" isWriteIn="false" />
        <choice choiceName="No" totalVotes="1102423" isWriteIn="false" />
      </choices>
    </contest>
  </contests>
</electionResult>
```

**No winner field in XML** — `is_winner` is always `None`.
**No official/unofficial flag** — `result_type` is always `'unofficial'`.
**Cache key:** `az_sos:ver:{election_pk}`

**Files changed:**
- Create: `backend/results/adapters/az.py`
- Create: `backend/results/tests/test_az_adapter.py`
- Modify: `backend/results/apps.py` — add `az` to the import in `ready()`

---

## Task 1: Parser helpers + XML parsing (TDD)

**Files:**
- Create: `backend/results/adapters/az.py` (skeleton + helpers)
- Create: `backend/results/tests/test_az_adapter.py`

- [ ] **Step 1: Write the failing parser tests**

Create `backend/results/tests/test_az_adapter.py`:

```python
"""
Unit tests for the Arizona SOS results adapter.
FTP calls are mocked; no network access required.
"""
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from results.adapters.az import (
    ArizonaAdapter,
    _build_url,
    _derive_election_name,
    _parse_results,
    _safe_int,
)

# ---------------------------------------------------------------------------
# Shared test XML
# ---------------------------------------------------------------------------

_SAMPLE_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <electionResult>
      <electionInformation>
        <resultsTimestamp>2026-07-21T20:15:00.000</resultsTimestamp>
        <electionName>2026 Primary Election</electionName>
        <electionDate>2026-07-21</electionDate>
        <fileId>12500</fileId>
      </electionInformation>
      <voterTurnout>
        <jurisdictions>
          <jurisdiction key="0" name="State" totalVoters="4200000"
              ballotsCast="1400000" voterTurnout="33.33"
              precinctsParticipating="1800" precinctsReported="1800"
              precinctsReportingPercent="100.00"
              earlyBallotsRemaining="0" provisionalBallotsRemaining="0"
              ballotsReadyToProcess="0" ballotsRemaining="0"
              ballotProcessingCompletedPercentage="100.00" />
        </jurisdictions>
      </voterTurnout>
      <contests>
        <contest key="100" contestLongName="U.S. Senator (DEM)"
                 districtKey="1" districtName="Federal Statewide"
                 numberToElect="1" termYears="6" isQuestion="false"
                 countiesParticipating="15" countiesReported="15"
                 precinctsParticipating="1800" precinctsReported="1800"
                 precinctsReportingPercent="100.00">
          <choices>
            <choice key="200" choiceName="Smith, Jane" partyKey="3"
                    party="DEM" totalVotes="400000" isWriteIn="false" />
            <choice key="201" choiceName="Jones, Bob" partyKey="3"
                    party="DEM" totalVotes="300000" isWriteIn="false" />
            <choice key="202" choiceName="Write-In" partyKey="1"
                    party="IND" totalVotes="500" isWriteIn="true" />
          </choices>
          <jurisdictions>
            <jurisdiction key="0" name="State" votes="700500">
              <voteTypes>
                <voteType voteTypeName="Polling Place" votes="50000" />
                <voteType voteTypeName="Early Ballots" votes="650000" />
              </voteTypes>
            </jurisdiction>
          </jurisdictions>
        </contest>
        <contest key="101"
                 contestLongName="Shall Justice X be retained in office?"
                 districtKey="42" districtName="AZ Supreme Court"
                 termYears="0" isQuestion="true"
                 countiesParticipating="15" countiesReported="15"
                 precinctsParticipating="1800" precinctsReported="1800"
                 precinctsReportingPercent="100.00">
          <choices>
            <choice choiceName="Yes" totalVotes="800000" isWriteIn="false" />
            <choice choiceName="No" totalVotes="600000" isWriteIn="false" />
          </choices>
        </contest>
      </contests>
    </electionResult>
""").encode()


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------

def test_safe_int_integer():
    assert _safe_int(42) == 42

def test_safe_int_string():
    assert _safe_int("498927") == 498927

def test_safe_int_comma_string():
    assert _safe_int("1,190,172") == 1190172

def test_safe_int_none():
    assert _safe_int(None) == 0

def test_safe_int_invalid():
    assert _safe_int("n/a") == 0


# ---------------------------------------------------------------------------
# _parse_results
# ---------------------------------------------------------------------------

def test_parse_results_returns_file_id():
    file_id, _ = _parse_results(_SAMPLE_XML)
    assert file_id == "12500"

def test_parse_results_candidate_contest_row_count():
    _, rows = _parse_results(_SAMPLE_XML)
    candidate_rows = [r for r in rows if r.candidate_name is not None]
    assert len(candidate_rows) == 2  # Smith, Jones — Write-In has candidate_name=None

def test_parse_results_candidate_name_inverted():
    # XML "Last, First" must be stored as "First Last" to match Candidate.name from Stage 1
    _, rows = _parse_results(_SAMPLE_XML)
    smith = next(r for r in rows if r.candidate_name == "Jane Smith")
    assert smith.office_title == "U.S. Senator"   # party suffix stripped
    assert smith.option_label is None
    assert smith.vote_count == 400000
    assert smith.vote_pct is None
    assert smith.is_winner is None
    assert smith.result_type == "unofficial"
    assert smith.is_write_in_aggregate is False

def test_parse_results_write_in_generic_has_no_candidate_name():
    # Generic "Write-In" aggregate: candidate_name=None, attaches at race level
    _, rows = _parse_results(_SAMPLE_XML)
    write_in = next(r for r in rows if r.is_write_in_aggregate and r.candidate_name is None)
    assert write_in.vote_count == 500
    assert write_in.office_title == "U.S. Senator"

def test_parse_results_ballot_question_row_count():
    _, rows = _parse_results(_SAMPLE_XML)
    measure_rows = [r for r in rows if r.option_label is not None]
    assert len(measure_rows) == 2  # Yes + No

def test_parse_results_ballot_question_fields():
    _, rows = _parse_results(_SAMPLE_XML)
    yes_row = next(r for r in rows if r.option_label == "Yes")
    assert yes_row.candidate_name is None
    # Ballot question titles have no party suffix; normalize_contest_name is a no-op
    assert yes_row.office_title == "Shall Justice X be retained in office?"
    assert yes_row.vote_count == 800000
    assert yes_row.result_type == "unofficial"
    assert yes_row.is_write_in_aggregate is False

def test_parse_results_total_row_count():
    _, rows = _parse_results(_SAMPLE_XML)
    assert len(rows) == 5  # 2 candidates + 1 write-in aggregate + 2 ballot options

def test_parse_results_raw_contest_key():
    _, rows = _parse_results(_SAMPLE_XML)
    smith = next(r for r in rows if r.candidate_name == "Smith, Jane")
    assert smith.raw["contestKey"] == "100"
    assert smith.raw["choiceKey"] == "200"

def test_parse_results_question_no_choice_key():
    # Ballot question choices have no key attribute — raw should not raise
    _, rows = _parse_results(_SAMPLE_XML)
    yes_row = next(r for r in rows if r.option_label == "Yes")
    assert yes_row.raw.get("choiceKey", "") == ""

def test_parse_results_empty_contests():
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<electionResult>
  <electionInformation>
    <fileId>99</fileId>
  </electionInformation>
  <contests />
</electionResult>"""
    file_id, rows = _parse_results(xml)
    assert file_id == "99"
    assert rows == []

def test_parse_results_missing_file_id():
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<electionResult>
  <electionInformation />
  <contests />
</electionResult>"""
    file_id, rows = _parse_results(xml)
    assert file_id == ""
    assert rows == []

def test_parse_results_office_title_normalized():
    """contestLongName party suffix must be stripped so title matches Stage 1 Race records."""
    xml = textwrap.dedent("""\
        <?xml version="1.0" encoding="utf-8"?>
        <electionResult>
          <electionInformation><fileId>1</fileId></electionInformation>
          <contests>
            <contest key="1" contestLongName="Governor (DEM)" isQuestion="false">
              <choices>
                <choice key="1" choiceName="Hobbs, Katie" party="DEM" totalVotes="100" isWriteIn="false"/>
              </choices>
            </contest>
          </contests>
        </electionResult>
    """).encode()
    _, rows = _parse_results(xml)
    assert rows[0].office_title == "Governor"       # party suffix stripped
    assert rows[0].candidate_name == "Katie Hobbs"  # "Last, First" → "First Last"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest results/tests/test_az_adapter.py -v --no-migrations 2>&1 | tail -20
```

Expected: `ImportError: cannot import name '_parse_results' from 'results.adapters.az'` (module doesn't exist yet)

- [ ] **Step 3: Write the skeleton + helpers**

Create `backend/results/adapters/az.py`:

```python
"""
Arizona (AZ) results adapter — AZ Secretary of State HTTPS XML feed.

Source: https://apps.azsos.gov/ftp/ElectionResults/{year}/State/{election_name}/Results.Summary.xml
Access: HTTPS via requests (confirmed HTTP 200; FTP also works but HTTPS preferred).
Schema: Results.Summary.xml — statewide candidate + ballot question totals.
        totalVotes on each <choice> is the statewide aggregate.

Required Election.source_metadata key (optional — auto-derived if absent):
    az_election_name  str  URL path segment, e.g. "2026 Primary Election"

Auto-derivation maps election_type:
    primary                → "Primary Election"
    general                → "General Election"
    presidential_preference → "Presidential Preference Election"
    <other>                → "{type.title()} Election"

Version caching:
    Cache key: az_sos:ver:{election_pk}
    Value:     fileId string from <electionInformation> (increments each publish)
    TTL:       30 days (written by ingest task after successful DB work)

Race name normalization:
    contestLongName values from the XML differ from CandidateList race names
    used by Stage 1 (integrations/az_sos). Both encode party in the name and
    use different abbreviations for US House races. normalize_contest_name()
    from integrations.az_sos.mappers is applied to every contestLongName so
    that ResultRow.office_title matches Race.office_title exactly, which is
    required for _process_race_results string-equality join to succeed.

Data notes:
    - No winner field in XML; is_winner is always None.
    - No official/unofficial flag; result_type is always 'unofficial'.
    - isWriteIn="true" on a <choice> → is_write_in_aggregate=True.
    - Ballot question choices have no key attribute; raw["choiceKey"] is "".
"""
from __future__ import annotations

import logging
import urllib.parse
from xml.etree import ElementTree as ET

import requests
from django.core.cache import cache

from integrations.az_sos.mappers import normalize_candidate_name, normalize_contest_name
from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_HTTPS_BASE = "https://apps.azsos.gov/ftp/ElectionResults"
_TIMEOUT = 60

_ELECTION_TYPE_TO_LABEL: dict[str, str] = {
    "primary": "Primary Election",
    "general": "General Election",
    "presidential_preference": "Presidential Preference Election",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_int(val, default: int = 0) -> int:
    try:
        return int(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return default


def _derive_election_name(election) -> str:
    year = election.election_date.year
    etype = (getattr(election, 'election_type', '') or '').lower().strip()
    label = _ELECTION_TYPE_TO_LABEL.get(etype) or f"{etype.replace('_', ' ').title()} Election"
    return f"{year} {label}"


def _build_url(election) -> str:
    meta = election.source_metadata or {}
    election_name = (meta.get('az_election_name') or '').strip() or _derive_election_name(election)
    year = election.election_date.year
    encoded_name = urllib.parse.quote(election_name)
    return f"{_HTTPS_BASE}/{year}/State/{encoded_name}/Results.Summary.xml"


def _fetch_xml(url: str, timeout: int = _TIMEOUT) -> bytes:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _parse_results(xml_bytes: bytes) -> tuple[str, list[ResultRow]]:
    """
    Parse Results.Summary.xml into (fileId, [ResultRow]).

    office_title on each ResultRow is normalize_contest_name(contestLongName)
    so it matches Race.office_title created by Stage 1 (integrations/az_sos).
    Returns ("", []) on empty or malformed input.
    """
    root = ET.fromstring(xml_bytes)

    info = root.find('electionInformation')
    file_id = (info.findtext('fileId') or '') if info is not None else ''

    rows: list[ResultRow] = []
    contests_el = root.find('contests')
    if contests_el is None:
        return file_id, rows

    for contest in contests_el.findall('contest'):
        is_question = contest.attrib.get('isQuestion', 'false').lower() == 'true'
        raw_name = (contest.attrib.get('contestLongName') or '').strip()
        # Normalize so office_title matches Race records created by Stage 1.
        office = normalize_contest_name(raw_name) if raw_name else None
        contest_key = contest.attrib.get('key', '')

        # Use direct path choices/choice — not .//choice — to avoid any
        # unintentional descent into nested jurisdiction blocks.
        for choice in contest.findall('choices/choice'):
            raw_choice_name = (choice.attrib.get('choiceName') or '').strip()
            if not raw_choice_name:
                continue
            total = _safe_int(choice.attrib.get('totalVotes', 0))
            xml_is_write_in = choice.attrib.get('isWriteIn', 'false').lower() == 'true'
            choice_key = choice.attrib.get('key', '')

            if is_question:
                candidate_name = None
                option_label = raw_choice_name
                is_write_in_aggregate = False
            else:
                # XML names are "Last, First"; normalize to "First Last" to match
                # Candidate.name stored by Stage 1. Generic "Write-In" aggregate
                # returns candidate_name=None so it attaches at the race level.
                candidate_name, is_write_in_aggregate = normalize_candidate_name(raw_choice_name)
                option_label = None

            rows.append(ResultRow(
                office_title=office,
                candidate_name=candidate_name,
                option_label=option_label,
                vote_count=total,
                vote_pct=None,
                is_winner=None,
                result_type='unofficial',
                is_write_in_aggregate=is_write_in_aggregate or xml_is_write_in,
                raw={'contestKey': contest_key, 'choiceKey': choice_key},
            ))

    return file_id, rows
```

- [ ] **Step 4: Run tests — expect all parser tests to pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest results/tests/test_az_adapter.py -v --no-migrations -k "safe_int or parse_results" 2>&1 | tail -25
```

Expected: all `test_safe_int_*` and `test_parse_results_*` tests PASS. The adapter-level tests (not written yet) still ERROR.

- [ ] **Step 5: Commit**

```bash
git -C /data/Projects/CivicMirror/CivicMirror-API add \
    backend/results/adapters/az.py \
    backend/results/tests/test_az_adapter.py
git -C /data/Projects/CivicMirror/CivicMirror-API commit -m "feat(az): add AZ SOS adapter skeleton — parser helpers + tests"
```

---

## Task 2: URL builder tests + adapter class

**Files:**
- Modify: `backend/results/adapters/az.py` (add `ArizonaAdapter`)
- Modify: `backend/results/tests/test_az_adapter.py` (add URL + adapter tests)

- [ ] **Step 1: Write failing URL builder and adapter tests**

Append to `backend/results/tests/test_az_adapter.py`:

```python
# ---------------------------------------------------------------------------
# _derive_election_name / _build_ftp_url
# ---------------------------------------------------------------------------

from datetime import date


def _make_election(election_type: str, year: int, source_metadata: dict | None = None):
    """Build a minimal mock election object for URL tests."""
    m = MagicMock()
    m.election_date = date(year, 7, 21)   # AZ 2026 primary is July 21
    m.election_type = election_type
    m.source_metadata = source_metadata or {}
    return m


def test_derive_election_name_primary():
    e = _make_election("primary", 2026)
    assert _derive_election_name(e) == "2026 Primary Election"


def test_derive_election_name_general():
    e = _make_election("general", 2026)
    assert _derive_election_name(e) == "2026 General Election"


def test_derive_election_name_presidential_preference():
    e = _make_election("presidential_preference", 2024)
    assert _derive_election_name(e) == "2024 Presidential Preference Election"


def test_derive_election_name_unknown_type():
    e = _make_election("runoff", 2026)
    assert _derive_election_name(e) == "2026 Runoff Election"


def test_build_url_derived():
    e = _make_election("primary", 2026)
    url = _build_url(e)
    assert url == "https://apps.azsos.gov/ftp/ElectionResults/2026/State/2026%20Primary%20Election/Results.Summary.xml"


def test_build_url_source_metadata_override():
    e = _make_election("primary", 2026, {"az_election_name": "2026 Primary Election Special"})
    url = _build_url(e)
    assert "2026%20Primary%20Election%20Special" in url


def test_build_url_spaces_encoded():
    e = _make_election("general", 2026)
    url = _build_url(e)
    assert " " not in url
    assert "%20" in url


# ---------------------------------------------------------------------------
# ArizonaAdapter.fetch_results — mocked FTP
# ---------------------------------------------------------------------------

from results.adapters.az import ArizonaAdapter
from unittest.mock import patch


@pytest.fixture
def mock_election(db):
    from elections.models import Election
    return Election.objects.create(
        name="2026 Arizona Primary Election",
        state="AZ",
        election_date=date(2026, 7, 21),   # AZ HB2022: July 21, not July 28
        election_type="primary",
        source="az_sos",
        source_id="az_sos_2026_primary",   # matches Stage 1 source_id
        status=Election.Status.RESULTS_PENDING,
        jurisdiction_level=Election.JurisdictionLevel.STATE,
        source_metadata={},
    )


@pytest.mark.django_db
def test_fetch_results_returns_rows(mock_election):
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", return_value=_SAMPLE_XML):
        result = adapter.fetch_results(mock_election.election_date, mock_election.pk)
    assert len(result.rows) == 5
    assert result.mapping_confidence == "full"
    assert result.unchanged is False


@pytest.mark.django_db
def test_fetch_results_unchanged_on_second_call(mock_election):
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", return_value=_SAMPLE_XML):
        result1 = adapter.fetch_results(mock_election.election_date, mock_election.pk)
        assert result1.source_version == "12500"  # fileId from sample XML
        # Simulate the ingest task writing the version cache after first run
        from django.core.cache import cache
        cache.set(adapter.version_cache_key(mock_election.pk), result1.source_version)
        result2 = adapter.fetch_results(mock_election.election_date, mock_election.pk)
    assert result2.unchanged is True
    assert result2.rows == []


@pytest.mark.django_db
def test_fetch_results_missing_election():
    adapter = ArizonaAdapter()
    result = adapter.fetch_results(date(2026, 7, 21), election_id=999999)
    assert result.mapping_confidence == "none"
    assert "not found" in result.notes


@pytest.mark.django_db
def test_fetch_results_no_election_type_falls_back_to_metadata(mock_election):
    mock_election.election_type = ""
    mock_election.source_metadata = {"az_election_name": "2026 Primary Election"}
    mock_election.save()
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", return_value=_SAMPLE_XML) as mock_fetch:
        adapter.fetch_results(mock_election.election_date, mock_election.pk)
    called_url = mock_fetch.call_args[0][0]
    assert "2026%20Primary%20Election" in called_url


@pytest.mark.django_db
def test_fetch_results_error_raises(mock_election):
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", side_effect=OSError("connection error")):
        with pytest.raises(OSError):
            adapter.fetch_results(mock_election.election_date, mock_election.pk)


@pytest.mark.django_db
def test_fetch_results_source_url_is_https(mock_election):
    adapter = ArizonaAdapter()
    with patch("results.adapters.az._fetch_xml", return_value=_SAMPLE_XML):
        result = adapter.fetch_results(mock_election.election_date, mock_election.pk)
    assert result.source_url.startswith("https://apps.azsos.gov")
```

- [ ] **Step 2: Run tests to confirm new ones fail**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest results/tests/test_az_adapter.py -v --no-migrations -k "derive or ftp_url or fetch_results" 2>&1 | tail -20
```

Expected: `_derive_election_name` and `_build_ftp_url` tests ERROR (not imported yet); `fetch_results` tests FAIL (class not defined yet).

- [ ] **Step 3: Add ArizonaAdapter to az.py**

Append to the end of `backend/results/adapters/az.py`:

```python
# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class ArizonaAdapter(StateResultsAdapter):
    state = "AZ"
    VERSION_CACHE_TIMEOUT = 86400 * 30  # 30 days

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return f"az_sos:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("az_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes=f'Election pk={election_id} not found',
            )

        url = _build_url(election)

        try:
            xml_bytes = _fetch_xml(url)
        except Exception as exc:
            logger.error("az_sos.adapter.fetch_failed url=%s: %s", url, exc)
            raise

        file_id, rows = _parse_results(xml_bytes)

        if not file_id:
            logger.warning("az_sos.adapter.no_file_id url=%s", url)

        cache_key = self.version_cache_key(election_id)
        if file_id and cache.get(cache_key) == file_id:
            logger.debug("az_sos.adapter.unchanged election=%d file_id=%s", election_id, file_id)
            return AdapterResult(
                rows=[], source_url=url, mapping_confidence='full',
                unchanged=True, source_version=file_id,
            )

        logger.info(
            "az_sos.adapter.fetched election=%d rows=%d file_id=%s",
            election_id, len(rows), file_id,
        )

        return AdapterResult(
            rows=rows,
            source_url=url,
            mapping_confidence='full',
            source_version=file_id,
        )
```

- [ ] **Step 4: Run the full test suite for az**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest results/tests/test_az_adapter.py -v --no-migrations 2>&1 | tail -30
```

Expected: all tests PASS.

- [ ] **Step 5: Register in apps.py**

Edit `backend/results/apps.py` — add `az` to the import line in `ready()`:

```python
def ready(self):
    from results.adapters import ar, az, ca, co, ct, ia, ma, sc, va, wv  # noqa: F401
```

- [ ] **Step 6: Smoke test — verify AZ is registered**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python manage.py shell -c "
from results.adapters import list_supported_states
states = list_supported_states()
print('Registered states:', states)
assert 'AZ' in states, 'AZ not registered!'
print('AZ adapter registered OK')
" 2>&1 | grep -v "^$\|imported"
```

Expected output includes `AZ` in the states list.

- [ ] **Step 7: Commit**

```bash
git -C /data/Projects/CivicMirror/CivicMirror-API add \
    backend/results/adapters/az.py \
    backend/results/tests/test_az_adapter.py \
    backend/results/apps.py
git -C /data/Projects/CivicMirror/CivicMirror-API commit -m "feat(az): add Arizona SOS results adapter

Fetches Results.Summary.xml from https://apps.azsos.gov/ftp/ElectionResults/.
Uses fileId for change detection (increments each publish). Applies
normalize_contest_name() to contestLongName so ResultRow.office_title matches
Race.office_title created by Stage 1 — required for _process_race_results join.
Handles candidate races and ballot questions; result_type always unofficial."
```

---

## Task 3: Live validation against real AZ FTP data

**Files:** None (read-only validation)

- [ ] **Step 1: Fetch live 2024 Primary XML via adapter logic**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python manage.py shell -c "
from results.adapters.az import _fetch_xml, _parse_results
import urllib.parse

url = 'ftp://ftp.azsos.gov/ElectionResults/2024/State/2024%20Primary%20Election/Results.Summary.xml'
xml = _fetch_xml(url)
timestamp, rows = _parse_results(xml)
print(f'Timestamp: {timestamp}')
print(f'Total rows: {len(rows)}')
candidate_rows = [r for r in rows if r.candidate_name]
question_rows = [r for r in rows if r.option_label]
print(f'Candidate rows: {len(candidate_rows)}')
print(f'Question rows: {len(question_rows)}')
print('Sample row:', rows[0])
" 2>&1 | grep -v "imported"
```

Expected: timestamp non-empty, >100 rows total, mix of candidate and question rows.

- [ ] **Step 2: Verify contest count matches known 2024 primary**

The 2024 AZ Primary XML has 142 candidate contests and 0 question contests (confirmed earlier).

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python manage.py shell -c "
from results.adapters.az import _fetch_xml, _parse_results

url = 'ftp://ftp.azsos.gov/ElectionResults/2024/State/2024%20Primary%20Election/Results.Summary.xml'
xml = _fetch_xml(url)
timestamp, rows = _parse_results(xml)
offices = {r.office_title for r in rows}
print(f'Distinct offices: {len(offices)}')
print('First 5 offices:', sorted(offices)[:5])
write_ins = [r for r in rows if r.is_write_in_aggregate]
print(f'Write-in rows: {len(write_ins)}')
assert all(r.result_type == 'unofficial' for r in rows), 'result_type mismatch'
print('All result_type=unofficial: OK')
" 2>&1 | grep -v "imported"
```

- [ ] **Step 3: Check 2026 FTP directory (confirm election name for July primary)**

```bash
python3 -c "
import ftplib
ftp = ftplib.FTP('ftp.azsos.gov', timeout=15)
ftp.login()
ftp.cwd('/ElectionResults/2026/State')
print('2026 election directories:')
ftp.retrlines('LIST')
ftp.quit()
" 2>&1
```

If the 2026 directory is empty or missing, that's expected — results won't appear until election night (July 28). The FTP listing confirms the directory structure for setting `az_election_name`.

- [ ] **Step 4: Admin setup instructions**

After the July 28 election, set `source_metadata` on the AZ primary election in Django admin:

```json
{"az_election_name": "2026 Primary Election"}
```

If `election_type` is correctly set to `"primary"` on the Election record, **no manual `source_metadata` setup is required** — the adapter derives the name automatically.

Verify the election record exists (created by Stage 1 `sync_az_elections`):

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python manage.py shell -c "
from elections.models import Election
qs = Election.objects.filter(state='AZ', election_date='2026-07-21')
for e in qs:
    print(f'id={e.pk} name={e.name} type={e.election_type} status={e.status} meta={e.source_metadata}')
" 2>&1 | grep -v "imported"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] HTTPS URL construction with year + election_name — Task 2 `_build_url`
- [x] `source_metadata['az_election_name']` override — Task 2 `_build_url`
- [x] Auto-derive from `election_type` — Task 2 `_derive_election_name`
- [x] XML parse — statewide totals from `totalVotes` on `<choice>` — Task 1 `_parse_results`
- [x] `normalize_contest_name` applied to every `contestLongName` — Task 1 `_parse_results`
- [x] Candidate races (`isQuestion=false`) → `candidate_name` — Task 1
- [x] Ballot questions (`isQuestion=true`) → `option_label` — Task 1
- [x] `isWriteIn=true` → `is_write_in_aggregate` — Task 1
- [x] No winner field → `is_winner=None` — Task 1
- [x] Version caching on `fileId` — Task 2 `ArizonaAdapter`
- [x] `unchanged=True` on cache hit — Task 2 `ArizonaAdapter`
- [x] `ResultsConfig.ready()` import — Task 2 Step 5
- [x] Live HTTPS validation — Task 3

**Cross-plan compatibility:**
- `normalize_contest_name` imported from `integrations.az_sos.mappers` — Stage 1 must be built first (or at minimum `mappers.py` must exist before Stage 2 tests run)
- Election date `2026-07-21` consistent with Stage 1 `AZ_ELECTIONS`
- `source_id="az_sos_2026_primary"` in test fixture consistent with Stage 1

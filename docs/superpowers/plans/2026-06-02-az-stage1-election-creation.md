# Arizona Stage 1 — Election + Race + Candidate Creation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `integrations/az_sos` — a self-contained Django integration that seeds AZ election records from hard-coded statutory dates, scrapes race + candidate data from `azcleanelections.gov/Custom/CandidateList`, and enriches each candidate with bio/social/website from `CandidateDetail`. No dependency on Google Civic API.

**Architecture:** Two-stage Celery task chain (`sync_az_elections` → `sync_az_candidate_details`). Stage 1 fetches the candidate list, fingerprints it, upserts Race + Candidate records for FEDERAL and STATE branches only. Stage 2 fetches CandidateDetail at 1 req/sec (delta-only: new candidates only). Wired into the internal trigger API and Cloud Scheduler.

**Tech Stack:** `requests` + `beautifulsoup4`/`lxml` (both already in `requirements/base.txt`); Django ORM + aggregation ingest; Celery; Redis cache for fingerprint dedup.

---

## Important Design Caveats (read before coding)

### 1. CCEC coverage may not be complete
`azcleanelections.gov` is operated by the AZ Citizens Clean Elections Commission. The 341-candidate count appears to match the full filed slate, but this has not been verified against the AZSOS official candidate list. Store `az_candidate_id` in `source_metadata` on every candidate so CCEC-sourced candidates are distinguishable if a supplemental source is added later. Task 6 includes an explicit cross-check step.

### 2. Stage 1 → Stage 2 race name normalization — real string differences confirmed from live data

**Actual strings from the 2024 Primary XML and live CandidateList:**

| CandidateList `<h3>` | XML `contestLongName` (party stripped) |
|---|---|
| `Governor` | `Governor` |
| `U.S. House of Rep. - District 1` | `U.S. Representative in Congress - District No. 1` |
| `State Senator - District 1` | `State Senator - District No.  1` ← **double space** |
| `State Representative - District 1` | `State Representative - District No.  1` ← **double space** |

Three normalization problems to solve simultaneously:
1. `U.S. Representative in Congress` ↔ `U.S. House of Rep.` — completely different strings
2. `District No. 1` ↔ `District 1` — "No." prefix that the list omits
3. `District No.  1` ← double space before district number in XML

Solution: regex-based extraction to a canonical form, not string-replacement of display names. `normalize_contest_name()` in `mappers.py` handles all three and is imported by both Stage 1 and Stage 2.

### 3. County/City races — out of scope for Stage 1
Scope the candidate list parse to `secBL1` (FEDERAL) and `secBL2`/`secBL3` (STATE-EXECUTIVE, STATE-LEGISLATIVE) only. County/city races (`secBL4`–`secBL7`) are absent from the AZSOS statewide XML results feed, their race name `<h3>` values can be non-unique within a county, and they cannot be joined to Stage 2 results. Skip them in Stage 1; they can be addressed separately if needed.

### 4. Candidate dedup uses stable external ID, not name
`ingest_candidate` keys on `(normalized_name, normalized_party)` per race. If a candidate's name has a minor spelling change between syncs, a duplicate row would be created. Use `az_candidate_id` as the stable identity: before calling `ingest_candidate`, check for an existing candidate with `source_metadata__az_candidate_id=entry.candidate_id` in the race. If found, update directly. Only call `ingest_candidate` for genuinely new candidates.

### 5. Election seeding runs unconditionally; fingerprint gates only candidate parsing
`_seed_elections()` runs before the fingerprint check on every invocation — this is intentional. The Election rows need to exist immediately. The fingerprint gate skips the candidate list parse (expensive, 341+ ingest operations) when nothing has changed. Tests and log messages should describe what's skipped as "candidate parsing", not the whole task.

---

## Key Reference Facts

**Election dates (hard-coded; source: AZ HB2022, signed 2026-02-06):**
- 2026 Primary: `2026-07-21`
- 2026 General: `2026-11-03`

**Real XML `contestLongName` values (confirmed 2024 Primary):**
```
'U.S. Representative in Congress - District No. 1 (DEM)'
'State Senator - District No.  1 (DEM)'   ← note double space
'State Representative - District No.  1 (DEM)'
'Governor (DEM)'
'Corporation Commissioner (DEM)'
```

**CandidateList `<h3>` race names (confirmed live):**
```
'U.S. House of Rep. - District 1'
'State Senator - District 1'
'State Representative - District 1'
'Governor'
'Corporation Commissioner'
```

**Party suffixes found in XML:** `(DEM)`, `(REP)`, `(GRN)`, `(LIB)`, `(NOL)`, `(NPA)`, `(IND)`

**Fingerprint cache key:** `az_sos:candidate_list_fingerprint`

**HTML structure (confirmed from live endpoint, relevant branches only):**
```html
<section id="secBL1">               <!-- FEDERAL - LEGISLATIVE -->
  <h3 class="branch">FEDERAL - LEGISLATIVE</h3>
  <section>
    <h3>U.S. House of Rep. - District 1</h3>
    <ul class="people">
      <li>
        <img class="viewmore" onclick="myPopup.ViewCand(5780);" />
        <div>
          <b>Amish Shah</b>
          <span class="party">Democratic</span>
        </div>
      </li>
    </ul>
  </section>
</section>
<section id="secBL2">STATE - EXECUTIVE races</section>
<section id="secBL3">STATE - LEGISLATIVE races</section>
<!-- secBL4–7: COUNTY/CITY — skip in Stage 1 -->
```

**Model fields verified:**
- `Election`: `state`, `election_type`, `election_date`, `jurisdiction_level`, `source_metadata`, `last_synced_at` ✓
- `Race`: `office_title`, `geography_scope`, `source_metadata`, `last_synced_at` — **no direct `state` field** (reach via `election__state`)
- `Candidate`: `candidate_status`, `CandidateStatus.RUNNING/WITHDRAWN`, `source_metadata` ✓
- `SyncLog`: `from ops.models import SyncLog`; fields `records_created`, `error_count`, `last_error` ✓

**ingest signatures verified against `aggregation/ingest.py`:**
```python
ingest_election(*, source, source_id, identity, fields) → (Election, created: bool)
ingest_race(*, election, source, identity, fields) → (Race, created: bool)
ingest_candidate(*, race, source, name, party, fields) → (Candidate, created: bool)
```

---

## Files

| Action | Path | Purpose |
|---|---|---|
| Create | `backend/integrations/az_sos/__init__.py` | Package marker |
| Create | `backend/integrations/az_sos/apps.py` | Django app config |
| Create | `backend/integrations/az_sos/exceptions.py` | AzSosError, AzSosRetryableError |
| Create | `backend/integrations/az_sos/client.py` | HTTP fetcher (CandidateList + CandidateDetail) |
| Create | `backend/integrations/az_sos/parsers.py` | HTML parsers |
| Create | `backend/integrations/az_sos/mappers.py` | Election dates, normalize_contest_name, party_abbrev |
| Create | `backend/integrations/az_sos/tasks.py` | sync_az_elections + sync_az_candidate_details |
| Create | `backend/integrations/az_sos/tests/__init__.py` | Package marker |
| Create | `backend/integrations/az_sos/tests/test_parsers.py` | Parser + mapper unit tests |
| Create | `backend/integrations/az_sos/tests/test_tasks.py` | Task integration tests |
| Modify | `backend/config/settings/base.py` | Add `integrations.az_sos` to INSTALLED_APPS |
| Modify | `backend/internal/task_locks.py` | Add `sync_az_sos` lock entry |
| Modify | `backend/internal/urls.py` | Add `tasks/sync-az-sos/` path |
| Modify | `backend/internal/views.py` | Import + trigger view |

---

## Task 0: Verify assumptions before writing code

**Files:** None (read-only)

- [ ] **Step 1: Confirm beautifulsoup4 + lxml are in requirements**

```bash
grep -E "beautifulsoup4|lxml" /data/Projects/CivicMirror/CivicMirror-API/backend/requirements/base.txt
```

Expected: both lines present. If missing, add them before proceeding.

- [ ] **Step 2: Confirm ingest signatures match the plan**

```bash
grep -n "^def ingest_" /data/Projects/CivicMirror/CivicMirror-API/backend/aggregation/ingest.py
```

Expected:
```
def ingest_election(*, source, source_id, identity, fields):
def ingest_race(*, election, source, identity, fields):
def ingest_candidate(*, race, source, name, party, fields):
```

- [ ] **Step 3: Confirm Race has no direct state field**

```bash
grep -n "state" /data/Projects/CivicMirror/CivicMirror-API/backend/elections/models.py | grep "models\."
```

Expected: `state` appears on `Election` (line ~40) and `DistrictRecord`, but NOT on `Race` (line ~79). Race reaches state via `race.election.state`.

- [ ] **Step 4: Verify live XML strings match the plan's reference facts**

```bash
curl -s "ftp://ftp.azsos.gov/ElectionResults/2024/State/2024%20Primary%20Election/Results.Summary.xml" | python3 -c "
from xml.etree import ElementTree as ET
import sys
root = ET.parse(sys.stdin).getroot()
names = sorted({c.attrib['contestLongName'] for c in root.find('contests').findall('contest')})
for n in names:
    if any(k in n for k in ['Representative', 'Senator', 'Governor', 'Corporation']):
        print(repr(n))
" | head -10
```

Expected output matches the Key Reference Facts table above (double space in District No., "U.S. Representative in Congress", etc.).

---

## Task 1: Exceptions + parsers (TDD)

**Files:**
- Create: `backend/integrations/az_sos/exceptions.py`
- Create: `backend/integrations/az_sos/parsers.py`
- Create: `backend/integrations/az_sos/tests/__init__.py`
- Create: `backend/integrations/az_sos/tests/test_parsers.py`

- [ ] **Step 1: Create exceptions module**

Create `backend/integrations/az_sos/exceptions.py`:
```python
class AzSosError(Exception):
    """Non-retryable AZ SOS integration error."""

class AzSosRetryableError(AzSosError):
    """Transient error — Celery should retry."""
```

- [ ] **Step 2: Write failing parser tests**

Create `backend/integrations/az_sos/tests/__init__.py` (empty).

Create `backend/integrations/az_sos/tests/test_parsers.py`:

```python
"""Unit tests for az_sos HTML parsers. No network access."""
import textwrap
import pytest

from integrations.az_sos.parsers import (
    CandidateDetailData,
    CandidateListEntry,
    parse_candidate_detail,
    parse_candidate_list,
)

# ---------------------------------------------------------------------------
# Shared test HTML
# ---------------------------------------------------------------------------

_CANDIDATE_LIST_HTML = textwrap.dedent("""\
    <section id="secBL1">
      <h3 class="branch">FEDERAL - LEGISLATIVE</h3>
      <section>
        <h3>U.S. House of Rep. - District 1</h3>
        <ul class="people">
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(5780);" />
            <div>
              <b>Amish Shah</b>
              <span class="office">U.S. House of Rep. - District 1</span>
              <span class="party">Democratic</span>
            </div>
          </li>
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(5834);" />
            <div>
              <b>Alex Flores (Write-In)</b>
              <span class="party">Libertarian</span>
            </div>
          </li>
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(5621);" />
            <div>
              <b>Marlene Gal&#225;n-Woods</b>
              <span class="party">Democratic</span>
            </div>
          </li>
        </ul>
      </section>
    </section>
    <section id="secBL2">
      <h3 class="branch">STATE - EXECUTIVE</h3>
      <section>
        <h3>Governor</h3>
        <ul class="people">
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(5577);" />
            <div>
              <b>Katie Hobbs</b>
              <span class="party">Democratic</span>
            </div>
          </li>
        </ul>
      </section>
    </section>
    <section id="secBL4">
      <h3 class="branch">COUNTY</h3>
      <section>
        <h3>La Paz Supervisor</h3>
        <ul class="people">
          <li>
            <img class="viewmore" onclick="myPopup.ViewCand(9999);" />
            <div><b>Some Person</b><span class="party">Republican</span></div>
          </li>
        </ul>
      </section>
    </section>
""").encode()

_DETAIL_FULL_HTML = textwrap.dedent("""\
    <article class="person">
      <figure><img src="/custom/Picture/2380" alt="Joseph Chaplik"></figure>
      <h4>Joseph Chaplik</h4>
      <p>
        U.S. House of Rep. - District 1<br />
        Republican<br />
        Traditional Funding
      </p>
      <p>Website:&nbsp;&nbsp;<a href="https://www.josephchaplik.com/" target="_blank">www.josephchaplik.com/</a></p>
      <p>Donations:&nbsp;&nbsp;<a href="https://donate.example.com" target="_blank">donate.example.com</a></p>
      <p class="social">
        <a href="https://www.facebook.com/josephchaplik" target="_blank"><i class="fa-brands fa-facebook-f"></i></a>
        <a href="https://www.x.com/JosephChaplik" target="_blank"><i class="fa-brands fa-x-twitter"></i></a>
        <a href="https://www.youtube.com/@josephchaplik" target="_blank"><i class="fa-brands fa-youtube"></i></a>
      </p>
      <br style="clear:both;" />
      <p>Joseph Chaplik has 28 years of executive leadership experience.</p>
      <p><b>Statement</b><br />Representative Joseph Chaplik has a proven 3 term record.</p>
      <br />
    </article>
""").encode()

_DETAIL_SPARSE_HTML = textwrap.dedent("""\
    <article class="person">
      <figure><img src="/custom/Picture/0" alt="Alex Flores (Write-In)"></figure>
      <h4>Alex Flores (Write-In)</h4>
      <p>
        U.S. House of Rep. - District 2<br />
        Libertarian<br />
        Traditional Funding
      </p>
      <p class="social"></p>
      <br style="clear:both;" />
      <br />
    </article>
""").encode()


# ---------------------------------------------------------------------------
# parse_candidate_list — scope
# ---------------------------------------------------------------------------

def test_parse_list_skips_county_branches():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    county = [e for e in entries if e.branch == "COUNTY"]
    assert county == [], "County races should be excluded from Stage 1"

def test_parse_list_total_count_federal_and_state_only():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    assert len(entries) == 4   # 3 federal + 1 state-exec; county excluded

# ---------------------------------------------------------------------------
# parse_candidate_list — field extraction
# ---------------------------------------------------------------------------

def test_parse_list_branch_assigned():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    assert any(e.branch == "FEDERAL - LEGISLATIVE" for e in entries)
    assert any(e.branch == "STATE - EXECUTIVE" for e in entries)

def test_parse_list_race_name():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    assert any(e.race_name == "U.S. House of Rep. - District 1" for e in entries)

def test_parse_list_candidate_id():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    amish = next(e for e in entries if "Amish" in e.name)
    assert amish.candidate_id == 5780

def test_parse_list_name_unescape():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    galán = next(e for e in entries if "Gal" in e.name)
    assert galán.name == "Marlene Galán-Woods"

def test_parse_list_write_in_flag():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    write_in = next(e for e in entries if e.is_write_in)
    assert write_in.name == "Alex Flores"

def test_parse_list_write_in_suffix_stripped():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    write_in = next(e for e in entries if e.is_write_in)
    assert "(Write-In)" not in write_in.name

def test_parse_list_party():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    amish = next(e for e in entries if "Amish" in e.name)
    assert amish.party == "Democratic"

def test_parse_list_governor():
    entries = parse_candidate_list(_CANDIDATE_LIST_HTML)
    gov = next(e for e in entries if e.race_name == "Governor")
    assert gov.name == "Katie Hobbs"
    assert gov.candidate_id == 5577

def test_parse_list_empty():
    assert parse_candidate_list(b"<html><body></body></html>") == []


# ---------------------------------------------------------------------------
# parse_candidate_detail — full record
# ---------------------------------------------------------------------------

def test_parse_detail_name():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).name == "Joseph Chaplik"

def test_parse_detail_office():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).office == "U.S. House of Rep. - District 1"

def test_parse_detail_party():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).party == "Republican"

def test_parse_detail_funding_type():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).funding_type == "Traditional Funding"

def test_parse_detail_website():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).website_url == "https://www.josephchaplik.com/"

def test_parse_detail_facebook():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).facebook == "https://www.facebook.com/josephchaplik"

def test_parse_detail_twitter():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).twitter == "https://www.x.com/JosephChaplik"

def test_parse_detail_youtube():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).youtube == "https://www.youtube.com/@josephchaplik"

def test_parse_detail_bio():
    assert "28 years" in parse_candidate_detail(_DETAIL_FULL_HTML).bio

def test_parse_detail_statement():
    d = parse_candidate_detail(_DETAIL_FULL_HTML)
    assert "proven 3 term record" in d.campaign_statement
    assert "Statement" not in d.campaign_statement  # prefix stripped

def test_parse_detail_photo():
    assert parse_candidate_detail(_DETAIL_FULL_HTML).photo_url == "/custom/Picture/2380"

# ---------------------------------------------------------------------------
# parse_candidate_detail — sparse (write-in)
# ---------------------------------------------------------------------------

def test_parse_detail_sparse_no_website():
    assert parse_candidate_detail(_DETAIL_SPARSE_HTML).website_url == ""

def test_parse_detail_sparse_no_social():
    d = parse_candidate_detail(_DETAIL_SPARSE_HTML)
    assert d.facebook == "" and d.twitter == ""

def test_parse_detail_sparse_no_bio():
    assert parse_candidate_detail(_DETAIL_SPARSE_HTML).bio == ""

def test_parse_detail_sparse_photo_zero():
    assert parse_candidate_detail(_DETAIL_SPARSE_HTML).photo_url == "/custom/Picture/0"

def test_parse_detail_missing_article():
    d = parse_candidate_detail(b"<html><body></body></html>")
    assert d.name == "" and d.bio == ""
```

- [ ] **Step 3: Run tests to confirm ImportError**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest integrations/az_sos/tests/test_parsers.py -v --no-migrations 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'integrations.az_sos'`

- [ ] **Step 4: Create parsers module**

Create `backend/integrations/az_sos/__init__.py` (empty).

Create `backend/integrations/az_sos/parsers.py`:

```python
"""
HTML parsers for azcleanelections.gov endpoints.

Scope: parse_candidate_list only yields entries from FEDERAL and STATE branches
(secBL1, secBL2, secBL3). County/city branches are excluded — their race names
are non-unique and they don't appear in the AZSOS statewide results XML.
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Branches to include in Stage 1 (statewide results XML has no county/city)
_INCLUDED_BRANCH_PREFIXES = ("FEDERAL", "STATE")

_WRITE_IN_SUFFIX = " (Write-In)"
_VIEWCAND_RE = re.compile(r"ViewCand\((\d+)\)")


@dataclass
class CandidateListEntry:
    branch: str          # e.g. "FEDERAL - LEGISLATIVE"
    race_name: str       # raw <h3> text, e.g. "U.S. House of Rep. - District 1"
    candidate_id: int    # from ViewCand({id}) onclick
    name: str            # HTML-unescaped; Write-In suffix stripped
    party: str           # e.g. "Democratic"
    is_write_in: bool


@dataclass
class CandidateDetailData:
    name: str = ""
    photo_url: str = ""
    office: str = ""
    party: str = ""
    funding_type: str = ""
    website_url: str = ""
    donation_url: str = ""
    facebook: str = ""
    twitter: str = ""
    youtube: str = ""
    instagram: str = ""
    bio: str = ""
    campaign_statement: str = ""


def parse_candidate_list(html_bytes: bytes) -> list[CandidateListEntry]:
    """
    Parse /Custom/CandidateList HTML into CandidateListEntry objects.
    Only FEDERAL and STATE branches are included; county/city are skipped.
    """
    soup = BeautifulSoup(html_bytes, "lxml")
    entries: list[CandidateListEntry] = []

    for branch_section in soup.find_all("section", id=re.compile(r"^secBL\d+$")):
        branch_h3 = branch_section.find("h3", class_="branch")
        branch = branch_h3.get_text(strip=True) if branch_h3 else ""

        if not any(branch.startswith(p) for p in _INCLUDED_BRANCH_PREFIXES):
            continue

        for race_section in branch_section.find_all("section", recursive=False):
            race_h3 = race_section.find("h3")
            race_name = race_h3.get_text(strip=True) if race_h3 else ""

            for li in race_section.find_all("li"):
                viewmore = li.find("img", class_="viewmore")
                if not viewmore:
                    continue
                m = _VIEWCAND_RE.search(viewmore.get("onclick", ""))
                if not m:
                    continue
                candidate_id = int(m.group(1))

                b_tag = li.find("b")
                raw_name = html_lib.unescape(b_tag.get_text(strip=True) if b_tag else "")
                is_write_in = raw_name.endswith(_WRITE_IN_SUFFIX)
                name = raw_name[: -len(_WRITE_IN_SUFFIX)].strip() if is_write_in else raw_name

                party_span = li.find("span", class_="party")
                party = party_span.get_text(strip=True) if party_span else ""

                entries.append(CandidateListEntry(
                    branch=branch,
                    race_name=race_name,
                    candidate_id=candidate_id,
                    name=name,
                    party=party,
                    is_write_in=is_write_in,
                ))

    return entries


def parse_candidate_detail(html_bytes: bytes) -> CandidateDetailData:
    """
    Parse /Custom/CandidateDetail HTML into CandidateDetailData.
    All fields are optional — write-in candidates have no website/bio/social.
    """
    soup = BeautifulSoup(html_bytes, "lxml")
    article = soup.find("article", class_="person")
    if not article:
        return CandidateDetailData()

    h4 = article.find("h4")
    name = h4.get_text(strip=True) if h4 else ""

    figure = article.find("figure")
    fig_img = figure.find("img") if figure else None
    photo_url = fig_img.get("src", "") if fig_img else ""

    # First <p> without a class: "Office\nParty\nFunding type" separated by <br>
    office = party = funding_type = ""
    first_p = article.find("p")
    if first_p and not first_p.get("class"):
        lines = [t.strip() for t in first_p.get_text("\n").split("\n") if t.strip()]
        if len(lines) > 0:
            office = lines[0]
        if len(lines) > 1:
            party = lines[1]
        if len(lines) > 2:
            funding_type = lines[2]

    website_url = donation_url = ""
    for p in article.find_all("p"):
        text = p.get_text(strip=True)
        a = p.find("a")
        if text.startswith("Website") and a:
            website_url = a.get("href", "")
        elif text.startswith("Donations") and a:
            donation_url = a.get("href", "")

    facebook = twitter = youtube = instagram = ""
    social_p = article.find("p", class_="social")
    if social_p:
        for a_tag in social_p.find_all("a"):
            icon = a_tag.find("i")
            if not icon:
                continue
            classes = " ".join(icon.get("class", []))
            href = a_tag.get("href", "")
            if "fa-facebook" in classes:
                facebook = href
            elif "fa-x-twitter" in classes:
                twitter = href
            elif "fa-youtube" in classes:
                youtube = href
            elif "fa-instagram" in classes:
                instagram = href

    bio = campaign_statement = ""
    for p in article.find_all("p"):
        if p.get("class"):
            continue
        text_stripped = p.get_text(strip=True)
        if not text_stripped or text_stripped.startswith("Website") or text_stripped.startswith("Donations"):
            continue
        b_tag = p.find("b")
        if b_tag and b_tag.get_text(strip=True) == "Statement":
            # Use separator="\n" to avoid "Statementtext" collapse;
            # split on first newline to separate the "Statement" label from the body
            lines = p.get_text(separator="\n").split("\n", 1)
            campaign_statement = lines[1].strip() if len(lines) > 1 else ""
        elif not bio and not b_tag:
            bio = text_stripped

    return CandidateDetailData(
        name=name, photo_url=photo_url, office=office, party=party,
        funding_type=funding_type, website_url=website_url, donation_url=donation_url,
        facebook=facebook, twitter=twitter, youtube=youtube, instagram=instagram,
        bio=bio, campaign_statement=campaign_statement,
    )
```

- [ ] **Step 5: Run all parser tests — expect pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest integrations/az_sos/tests/test_parsers.py -v --no-migrations 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git -C /data/Projects/CivicMirror/CivicMirror-API add \
    backend/integrations/az_sos/__init__.py \
    backend/integrations/az_sos/exceptions.py \
    backend/integrations/az_sos/parsers.py \
    backend/integrations/az_sos/tests/__init__.py \
    backend/integrations/az_sos/tests/test_parsers.py
git -C /data/Projects/CivicMirror/CivicMirror-API commit -m "feat(az): add az_sos parsers — CandidateList (FEDERAL+STATE only) and CandidateDetail"
```

---

## Task 2: Mappers (election dates + contest name normalization)

**Files:**
- Create: `backend/integrations/az_sos/mappers.py`
- Modify: `backend/integrations/az_sos/tests/test_parsers.py` (append mapper tests)

- [ ] **Step 1: Write failing mapper tests**

Append to `backend/integrations/az_sos/tests/test_parsers.py`:

```python
# ---------------------------------------------------------------------------
# mappers
# ---------------------------------------------------------------------------

from integrations.az_sos.mappers import AZ_ELECTIONS, normalize_contest_name, party_abbrev


def test_az_elections_primary_date():
    primary = next(e for e in AZ_ELECTIONS if e["election_type"] == "primary")
    assert primary["election_date"].isoformat() == "2026-07-21"


def test_az_elections_general_date():
    general = next(e for e in AZ_ELECTIONS if e["election_type"] == "general")
    assert general["election_date"].isoformat() == "2026-11-03"


# normalize_contest_name — party suffix stripping
def test_normalize_strips_dem_suffix():
    assert normalize_contest_name("Governor (DEM)") == "Governor"

def test_normalize_strips_rep_suffix():
    assert normalize_contest_name("Governor (REP)") == "Governor"

def test_normalize_strips_nol_suffix():
    assert normalize_contest_name("NOL Partisan Notice (NOL)") == "NOL Partisan Notice"

def test_normalize_no_suffix_unchanged():
    assert normalize_contest_name("Governor") == "Governor"

# normalize_contest_name — US House join (real strings from both sources)
def test_normalize_xml_us_house():
    # Real XML string after party strip → canonical
    result = normalize_contest_name("U.S. Representative in Congress - District No. 1 (DEM)")
    assert result == "U.S. House - District 1"

def test_normalize_list_us_house():
    # Real CandidateList string → same canonical
    result = normalize_contest_name("U.S. House of Rep. - District 1")
    assert result == "U.S. House - District 1"

def test_normalize_us_house_joins():
    xml = normalize_contest_name("U.S. Representative in Congress - District No. 7 (REP)")
    lst = normalize_contest_name("U.S. House of Rep. - District 7")
    assert xml == lst

# normalize_contest_name — state senator (double space in XML)
def test_normalize_xml_state_senator_double_space():
    # Real XML: double space before district number
    result = normalize_contest_name("State Senator - District No.  1 (DEM)")
    assert result == "State Senator - District 1"

def test_normalize_list_state_senator():
    result = normalize_contest_name("State Senator - District 1")
    assert result == "State Senator - District 1"

def test_normalize_state_senator_joins():
    xml = normalize_contest_name("State Senator - District No.  5 (REP)")
    lst = normalize_contest_name("State Senator - District 5")
    assert xml == lst

# normalize_contest_name — state representative (double space in XML)
def test_normalize_xml_state_rep_double_space():
    result = normalize_contest_name("State Representative - District No.  1 (DEM)")
    assert result == "State Representative - District 1"

def test_normalize_state_rep_joins():
    xml = normalize_contest_name("State Representative - District No.  12 (GRN)")
    lst = normalize_contest_name("State Representative - District 12")
    assert xml == lst

# normalize_contest_name — statewide races
def test_normalize_corporation_commissioner():
    assert normalize_contest_name("Corporation Commissioner (DEM)") == "Corporation Commissioner"

# party_abbrev
def test_party_abbrev_democratic():
    assert party_abbrev("Democratic") == "DEM"

def test_party_abbrev_republican():
    assert party_abbrev("Republican") == "REP"

def test_party_abbrev_libertarian():
    assert party_abbrev("Libertarian") == "LIB"

def test_party_abbrev_no_labels():
    assert party_abbrev("No Labels") == "NOL"   # AZ XML uses (NOL), not (NL)

def test_party_abbrev_nonpartisan():
    assert party_abbrev("Non-partisan") == "NPA"  # AZ XML uses (NPA), not (NP)

def test_party_abbrev_green():
    assert party_abbrev("Green") == "GRN"

# _geography_scope
from integrations.az_sos.mappers import geography_scope

def test_geography_scope_federal():
    assert geography_scope("FEDERAL - LEGISLATIVE") == "congressional_district"

def test_geography_scope_state_executive():
    assert geography_scope("STATE - EXECUTIVE") == "statewide"

def test_geography_scope_state_legislative():
    assert geography_scope("STATE - LEGISLATIVE") == "state_legislative_district"

# normalize_candidate_name
from integrations.az_sos.mappers import normalize_candidate_name

def test_normalize_candidate_regular():
    # XML "Last, First" → "First Last"
    name, is_wi = normalize_candidate_name("Gallego, Ruben")
    assert name == "Ruben Gallego"
    assert is_wi is False

def test_normalize_candidate_diacritic():
    name, is_wi = normalize_candidate_name("Galán-Woods, Marlene")
    assert name == "Marlene Galán-Woods"
    assert is_wi is False

def test_normalize_candidate_no_comma_unchanged():
    # Already "First Last" or single word — no inversion
    name, is_wi = normalize_candidate_name("Governor")
    assert name == "Governor"
    assert is_wi is False

def test_normalize_candidate_generic_write_in():
    # Generic aggregate → None (attaches at race level, not candidate)
    name, is_wi = normalize_candidate_name("Write-In")
    assert name is None
    assert is_wi is True

def test_normalize_candidate_named_write_in():
    # Named write-in → inverted name, is_write_in=True
    name, is_wi = normalize_candidate_name("Flores, Alex (Write-In)")
    assert name == "Alex Flores"
    assert is_wi is True

def test_normalize_candidate_named_write_in_suffix_stripped():
    name, _ = normalize_candidate_name("Flores, Alex (Write-In)")
    assert "(Write-In)" not in name
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest integrations/az_sos/tests/test_parsers.py -v --no-migrations -k "az_elections or normalize or party_abbrev or geography_scope or candidate_name" 2>&1 | tail -10
```

Expected: ImportError from mappers not yet created.

- [ ] **Step 3: Create mappers module**

Create `backend/integrations/az_sos/mappers.py`:

```python
"""
Static data and normalization helpers for the AZ SOS integration.

AZ_ELECTIONS:
    Hard-coded election records. Source: AZ HB2022, signed 2026-02-06.
    The primary was moved from "first Tuesday in August" to
    "second-to-last Tuesday in July". Do not derive from a formula.

normalize_contest_name:
    Canonical race name shared by Stage 1 (CandidateList) and Stage 2
    (Results XML). Both callers MUST use this function so the join works.

    Real source strings confirmed from 2024 Primary XML and live CandidateList:

    XML:  'U.S. Representative in Congress - District No. 1 (DEM)'
    List: 'U.S. House of Rep. - District 1'
    → canonical: 'U.S. House - District 1'

    XML:  'State Senator - District No.  1 (DEM)'   ← double space
    List: 'State Senator - District 1'
    → canonical: 'State Senator - District 1'

    Party suffixes found in XML: (DEM), (REP), (GRN), (LIB), (NOL), (NPA), (IND)
"""
from __future__ import annotations

import re
from datetime import date

# ---------------------------------------------------------------------------
# Election records
# ---------------------------------------------------------------------------

AZ_ELECTIONS: list[dict] = [
    {
        "name": "2026 Arizona Primary Election",
        "election_type": "primary",
        "election_date": date(2026, 7, 21),
        "source_id": "az_sos_2026_primary",
    },
    {
        "name": "2026 Arizona General Election",
        "election_type": "general",
        "election_date": date(2026, 11, 3),
        "source_id": "az_sos_2026_general",
    },
]

# ---------------------------------------------------------------------------
# Party abbreviation
# ---------------------------------------------------------------------------

_PARTY_MAP: dict[str, str] = {
    "democratic": "DEM",
    "republican": "REP",
    "libertarian": "LIB",
    "green": "GRN",
    "no labels": "NOL",     # AZ XML uses (NOL) not (NL)
    "non-partisan": "NPA",  # AZ XML uses (NPA) not (NP)
    "nonpartisan": "NPA",
    "independent": "IND",
    "american independent": "AIP",
}


def party_abbrev(party_name: str) -> str:
    return _PARTY_MAP.get(party_name.lower().strip(), party_name.upper()[:4])


# ---------------------------------------------------------------------------
# Contest name normalization
# ---------------------------------------------------------------------------

# Explicit allowlist of known AZ party suffixes — avoids matching Roman numerals,
# state abbreviations, or other 2–4 uppercase parentheticals.
_PARTY_SUFFIX_RE = re.compile(
    r"\s*\((DEM|REP|GRN|LIB|IND|NP|NL|NOL|NPA|AIP|OTH|NON)\)\s*$"
)

# "District No.  1" or "District No. 12" (single or double space before number)
# Handles the double space present in every AZ XML state legislative contest name.
_DISTRICT_NO_RE = re.compile(r"\bDistrict\s+No\.?\s+(\d+)\b")

# Both "U.S. Representative in Congress" (XML) and "U.S. House of Rep." (CandidateList)
# normalize to "U.S. House". The optional " - " after is consumed to avoid double dash.
_US_HOUSE_RE = re.compile(
    r"U\.S\.\s+(?:Representative\s+in\s+Congress|House\s+of\s+Rep\.)\s*-?\s*",
    re.IGNORECASE,
)


def normalize_contest_name(raw: str) -> str:
    """
    Return a canonical race name usable as a join key between Stage 1 races
    and Stage 2 XML results. Must be called on strings from both sources.

    Transformations (in order):
    1. Strip trailing party suffix from the explicit allowlist.
    2. Normalize "District No. X" / "District No.  X" → "District X".
    3. Normalize US House variants → "U.S. House - District X".
    4. Collapse internal whitespace.
    """
    name = _PARTY_SUFFIX_RE.sub("", raw).strip()
    name = _DISTRICT_NO_RE.sub(lambda m: f"District {m.group(1)}", name)
    name = _US_HOUSE_RE.sub("U.S. House - ", name)
    name = " ".join(name.split())
    return name


# ---------------------------------------------------------------------------
# Geography scope
# ---------------------------------------------------------------------------

def geography_scope(branch: str) -> str:
    """Map a CandidateList branch name to a Race.geography_scope value."""
    if "FEDERAL" in branch:
        return "congressional_district"
    if "CITY" in branch:
        return "city"
    if "COUNTY" in branch:
        return "county"
    if "EXECUTIVE" in branch:
        return "statewide"
    # STATE - LEGISLATIVE
    return "state_legislative_district"


# ---------------------------------------------------------------------------
# Candidate name normalization
# ---------------------------------------------------------------------------

_WRITE_IN_LABEL = "(Write-In)"
_GENERIC_WRITE_IN = "write-in"


def normalize_candidate_name(xml_name: str) -> tuple[str | None, bool]:
    """
    Convert an XML choiceName to (First Last form, is_write_in).

    XML stores names as "Last, First" (e.g. "Gallego, Ruben").
    Stage 1 stores names as "First Last" (e.g. "Ruben Gallego").
    The task runner matches ResultRow.candidate_name against Candidate.name
    by string equality, so this inversion is required for results to attach.

    Returns:
        (None, True)          — generic write-in aggregate ("Write-In")
                                result attaches at race level, not a candidate
        ("First Last", True)  — named write-in ("Flores, Alex (Write-In)")
        ("First Last", False) — regular candidate ("Gallego, Ruben")

    Name reversal is best-effort: multi-word first names, suffixes, and
    nicknames may cause mismatches. The task runner logs unmatched candidates
    as PARTIAL_RESULTS — they do not silently disappear.
    """
    is_write_in = _WRITE_IN_LABEL in xml_name
    name = xml_name.replace(_WRITE_IN_LABEL, "").strip()

    if name.lower() == _GENERIC_WRITE_IN:
        return None, True

    if "," in name:
        last, _, first = name.partition(",")
        name = f"{first.strip()} {last.strip()}".strip()

    return name or None, is_write_in
```

- [ ] **Step 4: Run mapper tests — expect pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest integrations/az_sos/tests/test_parsers.py -v --no-migrations -k "az_elections or normalize or party_abbrev or geography_scope or candidate_name" 2>&1 | tail -20
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C /data/Projects/CivicMirror/CivicMirror-API add \
    backend/integrations/az_sos/mappers.py \
    backend/integrations/az_sos/tests/test_parsers.py
git -C /data/Projects/CivicMirror/CivicMirror-API commit -m "feat(az): add mappers — election dates, contest normalization against real XML strings, party abbrev"
```

---

## Task 3: HTTP client

**Files:** Create `backend/integrations/az_sos/client.py`

- [ ] **Step 1: Create client**

Create `backend/integrations/az_sos/client.py`:

```python
"""
HTTP client for azcleanelections.gov.
No auth required. No Cloudflare gate observed.
Rate-limit: 1 req/sec enforced in fetch_candidate_detail.
"""
from __future__ import annotations

import logging
import time

import requests

from .exceptions import AzSosRetryableError

logger = logging.getLogger(__name__)

_BASE = "https://www.azcleanelections.gov"
_CANDIDATE_LIST_URL = f"{_BASE}/Custom/CandidateList"
_CANDIDATE_DETAIL_URL = f"{_BASE}/Custom/CandidateDetail/"
_TIMEOUT = 30
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class AzSosClient:
    def __init__(self, max_retries: int = 3, detail_req_interval: float = 1.0):
        self.max_retries = max_retries
        self.detail_req_interval = detail_req_interval
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.welshrd.com)"
        )
        self._last_detail_at: float | None = None

    def _get(self, url: str, params: dict | None = None) -> bytes:
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=_TIMEOUT)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise AzSosRetryableError(f"AZ SOS GET failed: {exc}") from exc
                time.sleep(2 ** attempt)
                continue
            if resp.status_code in _RETRYABLE_STATUSES:
                if attempt >= self.max_retries:
                    raise AzSosRetryableError(f"AZ SOS returned {resp.status_code} for {url}")
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.content
        raise AzSosRetryableError(f"AZ SOS retries exhausted for {url}")

    def fetch_candidate_list(self) -> bytes:
        return self._get(_CANDIDATE_LIST_URL)

    def fetch_candidate_detail(self, candidate_id: int) -> bytes:
        """Fetch with per-request 1 req/sec throttle."""
        if self._last_detail_at is not None:
            elapsed = time.monotonic() - self._last_detail_at
            if elapsed < self.detail_req_interval:
                time.sleep(self.detail_req_interval - elapsed)
        content = self._get(_CANDIDATE_DETAIL_URL, params={"id": candidate_id})
        self._last_detail_at = time.monotonic()
        return content
```

- [ ] **Step 2: Commit**

```bash
git -C /data/Projects/CivicMirror/CivicMirror-API add backend/integrations/az_sos/client.py
git -C /data/Projects/CivicMirror/CivicMirror-API commit -m "feat(az): add AzSosClient with 1 req/sec rate limit on CandidateDetail"
```

---

## Task 4: Tasks

**Files:**
- Create: `backend/integrations/az_sos/tasks.py`
- Create: `backend/integrations/az_sos/tests/test_tasks.py`

- [ ] **Step 1: Write failing task tests**

Create `backend/integrations/az_sos/tests/test_tasks.py`:

```python
"""Integration tests for az_sos tasks. HTTP calls are mocked."""
from datetime import date
from unittest.mock import patch, MagicMock
import pytest

from integrations.az_sos.parsers import CandidateListEntry, CandidateDetailData


@pytest.fixture
def mock_entries():
    return [
        CandidateListEntry("STATE - EXECUTIVE", "Governor", 5577, "Katie Hobbs", "Democratic", False),
        CandidateListEntry("STATE - EXECUTIVE", "Governor", 5601, "Andy Biggs", "Republican", False),
        CandidateListEntry("FEDERAL - LEGISLATIVE", "U.S. House of Rep. - District 1", 5780, "Amish Shah", "Democratic", False),
    ]


def _patch_sync(mock_entries, fingerprint="new123", cached_fingerprint=None):
    """Common patch context for sync_az_elections tests."""
    import hashlib
    expected_fp = hashlib.md5(b"<html>mock</html>").hexdigest()
    return [
        patch("integrations.az_sos.tasks.AzSosClient"),
        patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries),
        patch("integrations.az_sos.tasks.cache"),
        patch("integrations.az_sos.tasks.sync_az_candidate_details"),
    ]


@pytest.mark.django_db
def test_sync_elections_creates_election_records(mock_entries):
    from integrations.az_sos.tasks import sync_az_elections
    from elections.models import Election

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):

        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None  # no cached fingerprint → run parse

        sync_az_elections.apply()

    assert Election.objects.filter(state="AZ", election_type="primary").exists()
    assert Election.objects.filter(state="AZ", election_type="general").exists()


@pytest.mark.django_db
def test_sync_elections_creates_races(mock_entries):
    from integrations.az_sos.tasks import sync_az_elections
    from elections.models import Race

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):

        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None

        sync_az_elections.apply()

    # Use election__state, not state — Race has no direct state field
    assert Race.objects.filter(election__state="AZ", office_title="Governor").exists()
    assert Race.objects.filter(election__state="AZ", office_title="U.S. House - District 1").exists()


@pytest.mark.django_db
def test_sync_elections_creates_candidates(mock_entries):
    from integrations.az_sos.tasks import sync_az_elections
    from elections.models import Candidate

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):

        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None

        sync_az_elections.apply()

    assert Candidate.objects.filter(name="Katie Hobbs").exists()
    assert Candidate.objects.filter(name="Amish Shah").exists()


@pytest.mark.django_db
def test_sync_elections_skips_candidate_parsing_on_unchanged_fingerprint(mock_entries):
    """Elections are always seeded; candidate parsing is skipped on unchanged fingerprint."""
    from integrations.az_sos.tasks import sync_az_elections
    from elections.models import Election

    html = b"<html>mock</html>"
    import hashlib
    fp = hashlib.md5(html).hexdigest()

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list") as mock_parse, \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):

        MC.return_value.fetch_candidate_list.return_value = html
        mc.get.return_value = fp  # fingerprint matches → skip candidate parsing

        sync_az_elections.apply()

    # Elections ARE seeded even on fingerprint match
    assert Election.objects.filter(state="AZ", election_type="primary").exists()
    # Candidate parsing is NOT called
    mock_parse.assert_not_called()


@pytest.mark.django_db
def test_sync_elections_uses_stable_candidate_id_for_dedup(mock_entries):
    """Second sync with same candidates should not create duplicates."""
    from integrations.az_sos.tasks import sync_az_elections
    from elections.models import Candidate

    def run():
        with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
             patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
             patch("integrations.az_sos.tasks.cache") as mc, \
             patch("integrations.az_sos.tasks.sync_az_candidate_details"):
            MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
            mc.get.return_value = None
            sync_az_elections.apply()

    run()
    count_after_first = Candidate.objects.filter(name="Katie Hobbs").count()
    run()
    count_after_second = Candidate.objects.filter(name="Katie Hobbs").count()
    assert count_after_first == count_after_second == 1


@pytest.mark.django_db
def test_sync_elections_queues_detail_task(mock_entries):
    from integrations.az_sos.tasks import sync_az_elections

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details") as mock_detail:

        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None

        sync_az_elections.apply()

    mock_detail.delay.assert_called_once()


@pytest.mark.django_db
def test_sync_candidate_details_enriches_metadata(mock_entries):
    from integrations.az_sos.tasks import sync_az_elections, sync_az_candidate_details
    from elections.models import Candidate, Election

    detail = CandidateDetailData(
        name="Katie Hobbs",
        website_url="https://katiehobbs.org/",
        bio="Katie Hobbs bio text.",
        funding_type="Traditional Funding",
        facebook="https://facebook.com/hobbskatie",
    )

    # First, seed candidates via Stage 1
    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):
        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None
        sync_az_elections.apply()

    election_pk = Election.objects.get(state="AZ", election_type="primary").pk

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_detail", return_value=detail):
        MC.return_value.fetch_candidate_detail.return_value = b"<article>mock</article>"
        sync_az_candidate_details.apply(args=[election_pk])

    hobbs = Candidate.objects.get(name="Katie Hobbs")
    assert hobbs.source_metadata.get("az_website") == "https://katiehobbs.org/"
    assert hobbs.source_metadata.get("az_bio") == "Katie Hobbs bio text."
    assert hobbs.source_metadata.get("az_facebook") == "https://facebook.com/hobbskatie"


@pytest.mark.django_db
def test_sync_candidate_details_skips_already_enriched(mock_entries):
    """Candidates with az_bio in source_metadata should not be re-fetched."""
    from integrations.az_sos.tasks import sync_az_elections, sync_az_candidate_details
    from elections.models import Candidate, Election

    detail = CandidateDetailData(name="Katie Hobbs", bio="bio")

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_list", return_value=mock_entries), \
         patch("integrations.az_sos.tasks.cache") as mc, \
         patch("integrations.az_sos.tasks.sync_az_candidate_details"):
        MC.return_value.fetch_candidate_list.return_value = b"<html>mock</html>"
        mc.get.return_value = None
        sync_az_elections.apply()

    # Pre-populate az_bio to simulate already-enriched candidates
    Candidate.objects.filter(name="Katie Hobbs").update(
        source_metadata={"az_candidate_id": 5577, "az_bio": "existing bio"}
    )

    election_pk = Election.objects.get(state="AZ", election_type="primary").pk

    with patch("integrations.az_sos.tasks.AzSosClient") as MC, \
         patch("integrations.az_sos.tasks.parse_candidate_detail", return_value=detail) as mock_parse:
        MC.return_value.fetch_candidate_detail.return_value = b"<article>mock</article>"
        sync_az_candidate_details.apply(args=[election_pk])

    # Hobbs should NOT have been re-fetched
    hobbs = Candidate.objects.get(name="Katie Hobbs")
    assert hobbs.source_metadata.get("az_bio") == "existing bio"
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest integrations/az_sos/tests/test_tasks.py -v --no-migrations 2>&1 | tail -5
```

Expected: ImportError — tasks module not yet created.

- [ ] **Step 3: Create tasks module**

Create `backend/integrations/az_sos/tasks.py`:

```python
"""
AZ SOS Celery tasks.

sync_az_elections (Stage 1a):
    Always seeds Election records first (cheap; rows must exist).
    Fetches CandidateList HTML and fingerprints it.
    If unchanged → skips candidate parsing (log "candidate parsing skipped").
    If changed → upserts Race + Candidate records for FEDERAL + STATE branches.
    Deduplicates candidates by az_candidate_id (stable external key), not name.
    Marks candidates absent from this run as WITHDRAWN.
    Enqueues sync_az_candidate_details.

sync_az_candidate_details (Stage 1b):
    Fetches CandidateDetail at 1 req/sec for candidates that have az_candidate_id
    but lack az_bio in source_metadata (new candidates only; does not re-fetch).
"""
from __future__ import annotations

import hashlib
import logging

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

from elections.models import Candidate, Election, Race
from ops.models import SyncLog

from .client import AzSosClient
from .exceptions import AzSosError, AzSosRetryableError
from .mappers import AZ_ELECTIONS, geography_scope, normalize_candidate_name, normalize_contest_name, party_abbrev
from .parsers import parse_candidate_detail, parse_candidate_list

logger = logging.getLogger(__name__)

_FINGERPRINT_CACHE_KEY = "az_sos:candidate_list_fingerprint"
_FINGERPRINT_CACHE_TTL = 90 * 24 * 60 * 60  # 90 days


def _seed_elections() -> dict[str, Election]:
    """Upsert Election records from AZ_ELECTIONS. Runs every invocation."""
    from aggregation import ingest
    elections: dict[str, Election] = {}
    for spec in AZ_ELECTIONS:
        election, _ = ingest.ingest_election(
            source="az_sos",
            source_id=spec["source_id"],
            identity={
                "state": "AZ",
                "election_type": spec["election_type"],
                "election_date": spec["election_date"],
                "jurisdiction_level": Election.JurisdictionLevel.STATE,
            },
            fields={
                "name": spec["name"],
                "status": (
                    Election.Status.UPCOMING
                    if spec["election_date"] > timezone.localdate()
                    else Election.Status.RESULTS_PENDING
                ),
            },
        )
        elections[spec["election_type"]] = election
    return elections


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_az_elections(self):
    """Stage 1a: seed elections + upsert races/candidates from CandidateList."""
    from aggregation import ingest

    sync_log = SyncLog.objects.create(
        source="az_sos",
        task_name="sync_az_elections",
        status=SyncLog.Status.STARTED,
    )

    try:
        # Elections always seeded, regardless of fingerprint.
        elections = _seed_elections()
        primary = elections["primary"]

        client = AzSosClient()
        html_bytes = client.fetch_candidate_list()
        fingerprint = hashlib.md5(html_bytes).hexdigest()

        if cache.get(_FINGERPRINT_CACHE_KEY) == fingerprint:
            logger.info("az_sos.sync_elections.candidate_parsing_skipped fingerprint=%s", fingerprint)
            sync_log.notes = "CandidateList unchanged; candidate parsing skipped"
            sync_log.status = SyncLog.Status.COMPLETED
            sync_log.completed_at = timezone.now()
            sync_log.save(update_fields=["notes", "status", "completed_at"])
            return {"created_candidates": 0, "skipped": True}

        entries = parse_candidate_list(html_bytes)
        logger.info("az_sos.sync_elections.parsed entries=%d", len(entries))

        created_races = created_cands = updated_cands = 0
        seen_candidate_pks: set[int] = set()

        for entry in entries:
            canonical_name = normalize_contest_name(entry.race_name)

            race, race_created = ingest.ingest_race(
                election=primary,
                source="az_sos",
                identity={
                    "office_title": canonical_name,
                    "ocd_division_id": "",
                    "race_type": "candidate",
                },
                fields={
                    "office_title": canonical_name,
                    "jurisdiction": "Arizona",
                    "geography_scope": geography_scope(entry.branch),
                    "source_metadata": {"az_branch": entry.branch},
                },
            )
            if race_created:
                created_races += 1

            # Dedup by stable az_candidate_id, not (name, party).
            existing = Candidate.objects.filter(
                race=race,
                source_metadata__az_candidate_id=entry.candidate_id,
            ).first()

            if existing:
                seen_candidate_pks.add(existing.pk)
                updated_cands += 1
            else:
                cand, _ = ingest.ingest_candidate(
                    race=race,
                    source="az_sos",
                    name=entry.name,
                    party=party_abbrev(entry.party),
                    fields={
                        "source_metadata": {
                            "az_candidate_id": entry.candidate_id,
                            "az_is_write_in": entry.is_write_in,
                            "az_party_full": entry.party,
                        },
                    },
                )
                seen_candidate_pks.add(cand.pk)
                created_cands += 1

        withdrawn = (
            Candidate.objects
            .filter(
                race__election=primary,
                race__source_metadata__has_key="az_branch",
                candidate_status=Candidate.CandidateStatus.RUNNING,
            )
            .exclude(pk__in=seen_candidate_pks)
            .update(candidate_status=Candidate.CandidateStatus.WITHDRAWN)
        )
        if withdrawn:
            logger.info("az_sos.sync_elections.withdrawn count=%d", withdrawn)

        cache.set(_FINGERPRINT_CACHE_KEY, fingerprint, _FINGERPRINT_CACHE_TTL)
        primary.last_synced_at = timezone.now()
        primary.save(update_fields=["last_synced_at"])

        sync_az_candidate_details.delay(primary.pk)

        sync_log.records_created = created_cands
        sync_log.notes = f"races_created={created_races} withdrawn={withdrawn}"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["records_created", "notes", "status", "completed_at"])

        return {
            "created_races": created_races,
            "created_candidates": created_cands,
            "updated_candidates": updated_cands,
            "withdrawn": withdrawn,
        }

    except AzSosRetryableError as exc:
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.exception("az_sos.sync_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def sync_az_candidate_details(self, election_pk: int):
    """
    Stage 1b: enrich new candidates with bio/website/social.
    Only processes candidates that have az_candidate_id but lack az_bio —
    i.e., newly added since the last detail sweep.
    """
    try:
        election = Election.objects.get(pk=election_pk)
    except Election.DoesNotExist:
        logger.error("az_sos.sync_candidate_details.missing_election pk=%d", election_pk)
        return

    candidates_needing_detail = (
        Candidate.objects
        .filter(
            race__election=election,
            race__source_metadata__has_key="az_branch",
            source_metadata__has_key="az_candidate_id",
        )
        .exclude(source_metadata__has_key="az_bio")
    )

    total = candidates_needing_detail.count()
    if not total:
        logger.info("az_sos.sync_candidate_details.nothing_to_do election=%d", election_pk)
        return

    logger.info("az_sos.sync_candidate_details.start election=%d count=%d", election_pk, total)
    client = AzSosClient()
    enriched = errors = 0

    for candidate in candidates_needing_detail.iterator():
        az_id = (candidate.source_metadata or {}).get("az_candidate_id")
        if not az_id:
            continue
        try:
            html_bytes = client.fetch_candidate_detail(int(az_id))
            detail = parse_candidate_detail(html_bytes)
        except AzSosRetryableError as exc:
            logger.warning("az_sos.sync_candidate_details.fetch_failed id=%s: %s", az_id, exc)
            errors += 1
            continue

        meta = dict(candidate.source_metadata or {})
        meta.update({
            "az_bio": detail.bio,
            "az_campaign_statement": detail.campaign_statement,
            "az_website": detail.website_url,
            "az_donation_url": detail.donation_url,
            "az_facebook": detail.facebook,
            "az_twitter": detail.twitter,
            "az_youtube": detail.youtube,
            "az_instagram": detail.instagram,
            "az_funding_type": detail.funding_type,
            "az_photo_url": detail.photo_url,
        })
        Candidate.objects.filter(pk=candidate.pk).update(source_metadata=meta)
        enriched += 1

    logger.info(
        "az_sos.sync_candidate_details.done election=%d enriched=%d errors=%d",
        election_pk, enriched, errors,
    )
```

- [ ] **Step 4: Run task tests — expect pass**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest integrations/az_sos/tests/test_tasks.py -v --no-migrations 2>&1 | tail -20
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git -C /data/Projects/CivicMirror/CivicMirror-API add \
    backend/integrations/az_sos/tasks.py \
    backend/integrations/az_sos/tests/test_tasks.py
git -C /data/Projects/CivicMirror/CivicMirror-API commit -m "feat(az): add sync_az_elections + sync_az_candidate_details — stable ID dedup, fingerprint gate"
```

---

## Task 5: Wire into Django + internal API + Cloud Scheduler

**Files:**
- Create: `backend/integrations/az_sos/apps.py`
- Modify: `backend/config/settings/base.py`
- Modify: `backend/internal/task_locks.py`
- Modify: `backend/internal/urls.py`
- Modify: `backend/internal/views.py`

- [ ] **Step 1: Create apps.py**

Create `backend/integrations/az_sos/apps.py`:
```python
from django.apps import AppConfig

class AzSosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.az_sos"
    label = "az_sos"
```

- [ ] **Step 2: Add to INSTALLED_APPS**

In `backend/config/settings/base.py`, add `"integrations.az_sos"` alphabetically in the `integrations.*` block.

- [ ] **Step 3: Add task lock**

In `backend/internal/task_locks.py`, add to `TASK_LOCKS`:
```python
"sync_az_sos": (WINDOW_DAILY, 23 * _HOUR),
```

- [ ] **Step 4: Add URL + view**

In `backend/internal/urls.py`:
```python
path("tasks/sync-az-sos/", views.sync_az_sos_trigger, name="internal-sync-az-sos"),
```

In `backend/internal/views.py`, add import:
```python
from integrations.az_sos.tasks import sync_az_elections
```

And add view:
```python
@csrf_exempt
@require_POST
@require_internal_task_token
def sync_az_sos_trigger(request):
    return _trigger("sync_az_sos", sync_az_elections, request)
```

- [ ] **Step 5: Verify Django check**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
python manage.py check 2>&1 | tail -3
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 6: Add Cloud Scheduler job**

```bash
INTERNAL_TOKEN=$(gcloud secrets versions access latest --secret=INTERNAL_TASK_TOKEN --project=civicmirror-2026)
gcloud scheduler jobs create http sync-az-sos \
  --project=civicmirror-2026 \
  --location=us-central1 \
  --schedule="0 5 * * *" \
  --uri="https://api.civicmirror.welshrd.com/internal/tasks/sync-az-sos/" \
  --http-method=POST \
  --headers="Authorization=Bearer ${INTERNAL_TOKEN},Content-Type=application/json" \
  --time-zone="America/Phoenix" \
  --description="Daily AZ SOS candidate list sync (America/Phoenix — no DST)"
```

- [ ] **Step 7: Commit**

```bash
git -C /data/Projects/CivicMirror/CivicMirror-API add \
    backend/integrations/az_sos/apps.py \
    backend/config/settings/base.py \
    backend/internal/task_locks.py \
    backend/internal/urls.py \
    backend/internal/views.py
git -C /data/Projects/CivicMirror/CivicMirror-API commit -m "feat(az): wire az_sos into Django, task locks, internal trigger API, Cloud Scheduler"
```

---

## Task 6: Live validation

- [ ] **Step 1: Run full test suite**

```bash
cd /data/Projects/CivicMirror/CivicMirror-API/backend
pytest integrations/az_sos/ -v --no-migrations 2>&1 | tail -20
```

Expected: all PASS.

- [ ] **Step 2: Trigger live sync**

```bash
INTERNAL_TOKEN=$(gcloud secrets versions access latest --secret=INTERNAL_TASK_TOKEN --project=civicmirror-2026)
curl -s -X POST "https://api.civicmirror.welshrd.com/internal/tasks/sync-az-sos/" \
  -H "Authorization: Bearer $INTERNAL_TOKEN" -H "Content-Type: application/json"
```

Expected: `{"task_id": "..."}`.

- [ ] **Step 3: Monitor logs**

```bash
sleep 180 && gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="civicmirror-worker" AND textPayload=~"az_sos"' \
  --project=civicmirror-2026 --limit=20 --format="value(timestamp,textPayload)" 2>&1
```

Expected:
```
az_sos.sync_elections.parsed entries=341
az_sos.sync_candidate_details.start election=N count=341
az_sos.sync_candidate_details.done election=N enriched=341 errors=0
```

- [ ] **Step 4: Cross-check Governor race against AZSOS official list**

The AZSOS candidate filing page at `https://azsos.gov/elections/2026-primary-election` lists officially filed candidates. Compare the Governor race candidate count from that page against what `CandidateList` shows. This validates CCEC coverage completeness. Document any discrepancy in the research notes before declaring Stage 1 done.

- [ ] **Step 5: Verify normalize_contest_name works on real 2026 XML (post-election)**

After July 21, run:
```bash
curl -s "https://apps.azsos.gov/ftp/ElectionResults/2026/State/2026%20Primary%20Election/Results.Summary.xml" | python3 -c "
from xml.etree import ElementTree as ET
import sys
from integrations.az_sos.mappers import normalize_contest_name
# needs django setup or standalone import
root = ET.parse(sys.stdin).getroot()
for c in root.find('contests').findall('contest')[:10]:
    raw = c.attrib['contestLongName']
    print(repr(raw), '->', repr(normalize_contest_name(raw)))
"
```

Expected: all normalized names match Race records created in Stage 1.

---

## Self-Review

**All confirmed bugs addressed:**
- [x] normalize_contest_name built against real strings from both sources — real XML: `"U.S. Representative in Congress - District No. 1 (DEM)"`, real list: `"U.S. House of Rep. - District 1"` → both → `"U.S. House - District 1"`
- [x] Double space in XML `"District No.  1"` handled by `\s+` in `_DISTRICT_NO_RE`
- [x] `_PARTY_SUFFIX_RE` tightened to explicit allowlist `(DEM|REP|GRN|LIB|IND|NP|NL|NOL|NPA|AIP|OTH|NON)`
- [x] Election seeding unconditional; fingerprint only gates candidate parsing; test renamed and semantics clarified
- [x] `Race.objects.filter(election__state="AZ", ...)` — Race has no direct state field
- [x] Candidate dedup uses `source_metadata__az_candidate_id` as stable identity before calling `ingest_candidate`
- [x] County/city branches excluded via `_INCLUDED_BRANCH_PREFIXES`; test asserts exclusion
- [x] Statement parsing uses `get_text(separator="\n")` + split on first newline to avoid "Statementtext" collapse
- [x] `_geography_scope` renamed to `geography_scope`, exported, and has its own tests
- [x] Task 0 verification step added

**Confirmed correct (no fix needed):**
- ingest_election/race/candidate signatures match `aggregation/ingest.py` exactly ✓
- `SyncLog` from `ops.models` ✓ (verified from ca_sos/tasks.py)
- `Candidate.candidate_status`, `CandidateStatus.RUNNING/WITHDRAWN` ✓
- `Race.office_title`, `Race.geography_scope`, `Election.last_synced_at` ✓
- `beautifulsoup4` + `lxml` in `requirements/base.txt` ✓

**Cross-plan dependencies (Stage 2 imports from this module):**
- `normalize_contest_name` — required for race-level join
- `normalize_candidate_name` — required for candidate-level join (XML "Last, First" → Stage 1 "First Last")
- Stage 1 `mappers.py` must exist before Stage 2 tests can run
- `_PARTY_MAP` uses AZ XML codes (NOL, NPA) so stored party abbreviations are consistent with what Stage 2 will see in XML

# SC ENR System — URL Pattern & API Research

**Date:** 2026-05-26  
**Last Updated:** 2026-05-26 (rev 2)  
**Source:** Web research + HAR capture of `https://www.enr-scvotes.org/SC/` + direct inspection of `SCElectionResults.xml`  
**Purpose:** Programmatic discovery of SC election result URLs for import into Civitas

---

## 1. System Overview

South Carolina's Election Night Reporting (ENR) system runs on **Scytl/SOE Software's "Clarity" platform** — the same vendor used by dozens of states (Georgia, Colorado, Utah, etc.). The SC instance is hosted at:

```
https://www.enr-scvotes.org/SC/
```

The frontend is an **Angular SPA** served via **AWS CloudFront**. All election data is loaded via a JSON API with no authentication required.

The project also integrates with **VREMS** (`vrems.scvotes.sc.gov`) — a separate SC system for candidate filing data. ENR and VREMS are complementary but use completely separate ID namespaces. See Section 11 for how they fit together.

---

## 2. The Discovery API

### Endpoint

```
GET https://www.enr-scvotes.org/SC/elections.json?v={timestamp}
```

- `?v=` is a cache-buster only (`new Date().getTime()`). Any value works, or omit entirely.
- **No API key or authentication required.**
- **`Access-Control-Allow-Origin: *`** — callable directly from any frontend (no proxy needed).
- `Cache-Control: max-age=60, must-revalidate` — refreshes every 60 seconds.
- Served from CloudFront CDN; supports conditional GETs via ETag.

### Source Confirmation

Confirmed via HAR capture of a live browser session on `www.enr-scvotes.org`. The URL and cache-buster pattern were also extracted directly from the minified Angular JS bundle (`main.71154def8de6ec75.js`):

```javascript
this.electionsUrl = "elections.json?v=" + (new Date).getTime()
getElections() { return this.http.get(this.electionsUrl) }
```

### Current Behavior

As of 2026-05-26, returns `[]` (empty array) because no election is currently active/published. The file was last modified `2026-05-19`. This is expected — the list only contains elections that are currently published by the SC Election Commission.

### Response Schema

When elections are active, returns an array of objects. **The same election appears multiple times — once with `County: null` (state-level) and once per participating county. Each has a different `EID`.**

```json
[
  {
    "ElectionName": "2026 General Election",
    "Date": "11/03/2026 07:00:00",
    "State": "SC",
    "County": null,
    "EID": 130000
  },
  {
    "ElectionName": "2026 General Election",
    "Date": "11/03/2026 07:00:00",
    "State": "SC",
    "County": "Charleston",
    "EID": 121000
  },
  {
    "ElectionName": "2026 General Election",
    "Date": "11/03/2026 07:00:00",
    "State": "SC",
    "County": "Richland",
    "EID": 121001
  }
]
```

**Fields:**

| Field | Type | Notes |
|---|---|---|
| `ElectionName` | string | Human-readable name |
| `Date` | string | Format: `"MM/DD/YYYY HH:MM:SS"` |
| `State` | string | Always `"SC"` for this instance |
| `County` | string \| null | County name for county-level; `null` for state-level |
| `EID` | integer | Election ID — the only value needed to build the URL |

---

## 3. URL Structure

### How the Angular App Builds URLs

Extracted directly from the minified JS bundle (`main.71154def8de6ec75.js`):

```javascript
onClickGo(n) {
  const r = n.State;
  const o = n.County ? n.County.replace(/ /g, "_") : null;
  const i = o
    ? `${window.location.origin}/${r}/${o}/${n.EID}/`
    : `${window.location.origin}/${r}/${n.EID}/`;
  window.open(i, "_blank");
}
```

### Resulting URL Patterns

**State-level:**
```
https://www.enr-scvotes.org/SC/{EID}/
```

**County-level:**
```
https://www.enr-scvotes.org/SC/{County_with_underscores}/{EID}/
```

Examples:
```
https://www.enr-scvotes.org/SC/125820/
https://www.enr-scvotes.org/SC/Charleston/119138/
https://www.enr-scvotes.org/SC/York/116305/
```

### The `web.XXXXXX` Segment — Explained

URLs seen in the wild include an extra segment:
```
https://www.enr-scvotes.org/SC/125820/web.345435/#/summary
https://www.enr-scvotes.org/SC/Charleston/119138/web.317647/#/summary
```

**This segment is NOT in the `elections.json` data and NOT constructed by the app.** It is resolved via a **server-side redirect** when you navigate to `/{EID}/`. You never need to know it — the EID alone is sufficient for navigation. However, you DO need the resolved URL to construct the reports API path (see Section 6). Follow the redirect and store the resolved URL.

```python
def resolve_enr_url(eid: int, county: str | None = None) -> str:
    """Follow the server redirect to get the full web.XXXXXX URL."""
    base = "https://www.enr-scvotes.org/SC"
    path = f"{base}/{county.replace(' ','_')}/{eid}/" if county else f"{base}/{eid}/"
    resp = requests.get(path, allow_redirects=True, timeout=10)
    return resp.url  # now contains the full /web.XXXXXX/ path
```

---

## 4. The Two-ID System (For Reference)

When you encounter full ENR URLs in the wild, they contain two numeric IDs:

```
/SC/{ID1}/web.{ID2}/#/summary
/SC/{County}/{ID1}/web.{ID2}/#/summary
```

| ID | Role | Behavior |
|---|---|---|
| **ID1** (first number) | Jurisdiction-instance ID | Unique per jurisdiction per election. This is the `EID` from `elections.json`. |
| **ID2** (after `web.`) | Deployment/build ID | **Shared across all jurisdictions for the same election.** E.g., both SC state and Charleston county had `web.317647` for the same election cycle. |

**Cross-checking:** If you have one URL for an election, you can verify sibling county URLs by matching ID2 across them.

---

## 5. URL Format History

The Clarity platform has evolved. Older SC elections have different URL formats:

| Era | Format | Example |
|---|---|---|
| Oldest | `/{State}/{ID1}/{ID2}/en/summary.html` | `/SC/53424/149816/en/summary.html` |
| Mid (county) | `/{State}/{County}/{ID1}/{ID2}/en/summary.html` | `/SC/Georgetown/8584/11424/en/summary.html` |
| Transitional | `/{State}/{ID1}/Web02-state.{ID2}/` | `/SC/92124/Web02-state.222648/` |
| Current | `/{State}/{ID1}/web.{ID2}/#/summary` | `/SC/125820/web.345435/#/summary` |

**Implication:** Historical election URLs won't all follow the same pattern.

---

## 6. Data / Reports API

Once you have the full resolved URL (including the `web.XXXXXX` segment), structured data is available at:

```
# Detailed XML (precinct-level results)
{resolved_base_url}/reports/detailxml.zip

# Summary ZIP
{resolved_base_url}/reports/summary.zip
```

Example:
```
https://www.enr-scvotes.org/SC/125820/web.345435/reports/detailxml.zip
```

The XML format is the Clarity/SOE standard schema. The open-source Python library **[openelections/clarify](https://github.com/openelections/clarify)** can parse it:

```python
pip install clarify

import clarify
j = clarify.Jurisdiction(
    url='https://www.enr-scvotes.org/SC/125820/web.345435/en/summary.html',
    level='state'
)
j.report_url('xml')
# → '...reports/detailxml.zip'
```

---

## 7. County-Level Results Coverage

ENR provides **full county and precinct coverage automatically** via `elections.json`. No extra configuration is needed.

### What each level gives you

| Level | How obtained | Data available |
|---|---|---|
| **State** | `County: null` entry → `detailxml.zip` | Statewide totals + county-level breakdowns for statewide races |
| **County** | `County: "X"` entry → `detailxml.zip` | Per-county totals + precinct-level breakdown within that county |
| **Precinct** | Same `detailxml.zip` as county | Full precinct splits — already inside the county XML |

**Important:** For statewide races, the state-level `detailxml.zip` already contains county subtotals. Individual county ENR entries add precinct-level depth *within* each county. For most use cases, the state entry alone covers county totals without needing to fetch all 46 county entries.

### Edge cases

- **Nonpartisan/local-only races** (school boards, municipal elections): may appear in ENR under county entries but not in VREMS if run purely at the county level.
- **Runoffs**: appear as separate entries in both ENR and VREMS with different IDs. Deduplication logic must account for them.
- **Special elections**: short window in `elections.json` — easy to miss without a continuous poller.

---

## 8. Historical Data — What Actually Exists

### `SCElectionResults.xml` — Confirmed Dead Feed

The feed at `https://www.enr-scvotes.org/SC/SCElectionResults.xml` exists and is accessible, but is **not useful for historical backfill**. Direct inspection reveals:

```xml
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>SC's Election Results</title>
    <lastBuildDate>Tue, 07 May 2013 01:21:24 GMT</lastBuildDate>
    <pubDate>Tue, 07 May 2013 01:21:24 GMT</pubDate>
    <item>
      <title>2013 U.S. House District 1 Special Election</title>
      <link>http://www.enr-scvotes.org/SC/46180/index.html</link>
      <pubDate>Tue, 07 May 2013 01:21:24 GMT</pubDate>
    </item>
  </channel>
</rss>
```

It contains **a single entry from 2013** and has never been updated. It was part of the old platform and was abandoned when SC migrated to the Angular SPA. Do not build any automation against this feed.

### Historical Data Options

| Source | Coverage | Usefulness |
|---|---|---|
| `elections.json` | Active elections only, current platform | ✅ Primary going-forward source |
| `SCElectionResults.xml` | One entry, 2013 only, dead feed | ❌ Not useful |
| Known EID table (Section 9) | ~16 manually observed EIDs, 2013–2024 | ⚠️ Partial, needs manual verification |
| Wayback Machine | Archived snapshots of ENR pages | ⚠️ Possible but labor-intensive |

**Practical recommendation:** Treat ENR results as **current and future only**. Start polling `elections.json` now and persist every EID you see. For anything before that, use the known EID table (Section 9) as a manual seed and rely on VREMS for historical candidate data.

---

## 9. Known Election EIDs (Observed)

Collected from research — these are confirmed or inferred from observed URLs. Accuracy of date labels marked accordingly.

| Election | Scope | EID | Full URL Fragment | Confidence |
|---|---|---|---|---|
| 2024 General | State | 125820 | `/SC/125820/web.345435/` | ✅ Confirmed |
| 2024 General | Charleston | 119138 | `/SC/Charleston/119138/web.317647/` | ✅ Confirmed |
| 2024 General | State (alt?) | 119816 | `/SC/119816/web.317647/` | ⚠️ Unverified |
| 2022 General (approx) | State | 115412 | `/SC/115412/Web02-state.307150/` | ⚠️ Approx date |
| 2022 Primary (approx) | State | 114143 | `/SC/114143/Web02-state.289375/` | ⚠️ Approx date |
| 2022 Primary (approx) | State | 111639 | `/SC/111639/Web02-state.284278/` | ⚠️ Approx date |
| 2018 General | State | 92124 | `/SC/92124/Web02-state.222648/` | ⚠️ Approx date |
| ~2016 | State | 75708 | `/SC/75708/` (redirects) | ⚠️ Approx date |
| ~2014 | State | 64658 | `/SC/64658/index.html` | ⚠️ Approx date |
| ~2013 | State | 59148 | `/SC/59148/159444/en/summary.html` | ⚠️ Approx date |
| ~2013 | State | 53424 | `/SC/53424/149816/en/summary.html` | ⚠️ Approx date |
| 2013 Special | State | 46180 | `/SC/46180/index.htm` | ✅ Confirmed (from XML feed) |
| ~2013 | Richland | 106542 | `/SC/Richland/106542/Web02.264677/` | ⚠️ Approx date |
| ~2022 | Richland | 111679 | `/SC/Richland/111679/` | ⚠️ Approx date |
| ~2022 | York | 116305 | `/SC/York/116305/` | ⚠️ Approx date |
| ~2022 | Newberry | 102773 | `/SC/Newberry/102773/` | ⚠️ Approx date |
| ~2022 | Abbeville | 114144 | `/SC/Abbeville/114144/` | ⚠️ Approx date |

---

## 10. Implementation Recipe

### Polling for Active Elections (Python/Django)

```python
import time
import requests

def get_sc_enr_elections() -> list[dict]:
    resp = requests.get(
        "https://www.enr-scvotes.org/SC/elections.json",
        params={"v": int(time.time() * 1000)},
        timeout=10,
    )
    resp.raise_for_status()
    elections = resp.json()  # [] when no active election

    results = []
    for e in elections:
        county = e.get("County")
        eid = e["EID"]
        base_path = (
            f"SC/{county.replace(' ', '_')}/{eid}/"
            if county
            else f"SC/{eid}/"
        )
        results.append({
            "name": e["ElectionName"],
            "date": e["Date"].split(" ")[0],        # → "MM/DD/YYYY"
            "year": e["Date"].split("/")[2].split(" ")[0],
            "scope": "county" if county else "state",
            "county": county,
            "eid": eid,
            "enr_base_url": f"https://www.enr-scvotes.org/{base_path}",
        })
    return results


def resolve_enr_url(eid: int, county: str | None = None) -> str:
    """Follow the server-side redirect to get the full web.XXXXXX resolved URL."""
    base = "https://www.enr-scvotes.org/SC"
    path = f"{base}/{county.replace(' ', '_')}/{eid}/" if county else f"{base}/{eid}/"
    resp = requests.get(path, allow_redirects=True, timeout=10)
    return resp.url  # e.g. https://www.enr-scvotes.org/SC/125820/web.345435/
```

### Django Model Suggestion

```python
class ENRElection(models.Model):
    election_name = models.CharField(max_length=200)
    election_date = models.DateField()
    scope = models.CharField(max_length=10, choices=[('state', 'State'), ('county', 'County')])
    county = models.CharField(max_length=100, blank=True, null=True)
    eid = models.IntegerField()
    enr_base_url = models.URLField()           # unresolved: /SC/{EID}/
    enr_resolved_url = models.URLField(blank=True)  # resolved: /SC/{EID}/web.XXXXXX/
    # FK to your Election model once date-matched to a VREMS election
    election = models.ForeignKey(
        "elections.Election", null=True, blank=True, on_delete=models.SET_NULL
    )
    discovered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("eid", "county")]
```

---

## 11. ENR + VREMS Together — The Full Picture

ENR and VREMS are **complementary systems** that cover completely different aspects of an election. Neither is a substitute for the other.

### What each system provides

| | **VREMS** | **ENR / Clarity** |
|---|---|---|
| **System** | `vrems.scvotes.sc.gov` | `enr-scvotes.org` |
| **Purpose** | Candidate filing registry | Election night results |
| **Data** | Who is running, what office, party, filing status | Actual vote counts, precinct-level breakdowns |
| **Timing** | Available weeks/months before election | Available on election day and after |
| **ID namespace** | `electionId` (e.g. `22598`) | `EID` (e.g. `125820`) — **no shared key** |
| **County coverage** | County as a label/filter on races | Full county + precinct vote counts |
| **Current automation** | Fully automated via Celery tasks | Manual URL entry — automate using this doc |

### County-level data by system

**VREMS** tracks county as metadata on races, not as a results hierarchy:
- Statewide races (Governor, US Senate): `associated_counties` is empty — no county breakdown
- County/local races (Sheriff, County Council): `associated_counties` = `"Charleston"` etc. — tells you which county the race belongs to
- Multi-county districts (some SC House seats): `associated_counties` may list multiple counties

**ENR** provides actual vote counts at county and precinct level for every race in every entry it publishes.

### Linking the two systems

ENR `EID` and VREMS `electionId` have no shared key. The best join strategy is `election_date` + `county`:

```
VREMS                              ENR
─────────────────────────────────────────────────────
Race: "Sheriff"                    Results: vote counts
  filing_location: "Cherokee"        County: "Cherokee"
  associated_counties: "Cherokee"    EID: 121045
  election_date: 2026-11-03          Date: "11/03/2026"
  candidates: [A, B, C]              precinct breakdown
        │                                   │
        └──── match on county + date ───────┘
```

### Suggested module structure

Following the existing `sc_vrems` pattern, the ENR integration belongs at:

```
backend/integrations/sc_enr/
    __init__.py
    apps.py          # AppConfig, label="sc_enr"
    client.py        # get_elections(), resolve_url(), fetch_results()
    tasks.py         # poll_enr_elections(), sync_enr_results()
    mappers.py       # map_enr_election() — links to Election by date/county
    exceptions.py
    tests/
```

Task flow (mirrors VREMS two-stage pattern):
1. **`poll_enr_elections`** — hits `elections.json`, resolves URLs, upserts `ENRElection` records, attempts FK link to existing `Election` via date match
2. **`sync_enr_results`** — fetches `detailxml.zip` for each active election, parses via `ClarityAdapter`, upserts result records

**Key operational difference from VREMS:** ENR tasks only need to run during the ~60-day window around an election. VREMS runs year-round for filing data.

---

## 12. Key Takeaways

1. **`elections.json` is the canonical discovery API.** No scraping, no auth, CORS-open.
2. **EID is the only ID you need** to build a navigation URL — `web.XXXXXX` is resolved server-side.
3. **Follow the redirect** and store the resolved URL; you need it to construct the `reports/detailxml.zip` path.
4. **The feed only shows current/active elections.** Poll continuously during election season and persist every EID you see.
5. **`SCElectionResults.xml` is a dead end** — one entry from 2013, never updated, abandoned with the old platform.
6. **Historical data has no programmatic path.** Seed from the known EID table (Section 9) or accept the gap.
7. **County + precinct results are automatic** — every active county gets its own entry in `elections.json`.
8. **ENR and VREMS have no shared key.** Join them on `election_date` + `county`.
9. **ENR is results-only, election-season-only.** VREMS is candidate/filing data, year-round.

---

*Research conducted 2026-05-26. Sources: web research, HAR analysis of a live browser session on `www.enr-scvotes.org`, JS bundle inspection (`main.71154def8de6ec75.js`), and direct retrieval of `SCElectionResults.xml`.*

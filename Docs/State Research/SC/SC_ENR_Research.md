# SC ENR System — URL Pattern & API Research

**Date:** 2026-05-26  
**Source:** Web research + HAR capture of `https://www.enr-scvotes.org/SC/`  
**Purpose:** Programmatic discovery of SC election result URLs for import into Civitas

---

## 1. System Overview

South Carolina's Election Night Reporting (ENR) system runs on **Scytl/SOE Software's "Clarity" platform** — the same vendor used by dozens of states (Georgia, Colorado, Utah, etc.). The SC instance is hosted at:

```
https://www.enr-scvotes.org/SC/
```

The frontend is an **Angular SPA** served via **AWS CloudFront**. All election data is loaded via a JSON API with no authentication required.

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

### Current Behavior

As of 2026-05-26, returns `[]` (empty array) because no election is currently active/published. The file was last modified `2026-05-19`. This is expected — the list only contains elections that are currently published by the SC Election Commission.

### Response Schema

When elections are active, returns an array of objects:

```json
[
  {
    "ElectionName": "2024 General Election",
    "Date": "11/05/2024 07:00:00",
    "State": "SC",
    "County": null,
    "EID": 125820
  },
  {
    "ElectionName": "2024 General Election",
    "Date": "11/05/2024 07:00:00",
    "State": "SC",
    "County": "Charleston",
    "EID": 119138
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

**Note:** The same election appears multiple times — once with `County: null` (state-level) and once per participating county. Each has a different `EID`.

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

**This segment is NOT in the `elections.json` data and NOT constructed by the app.** It is resolved via a **server-side redirect** when you navigate to `/{EID}/`. You never need to know it — the EID alone is sufficient.

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

Once you have a full URL (either from `elections.json` + `EID`, or a known URL), structured data is available at:

```
# Detailed XML (precinct-level results)
{base_url}/reports/detailxml.zip

# Summary ZIP
{base_url}/reports/summary.zip
```

Where `{base_url}` is the full resolved URL including the `web.` segment, e.g.:
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

## 7. Historical Elections Feed

For elections that are no longer listed in `elections.json`, a secondary XML/RSS feed exists:

```
https://www.enr-scvotes.org/SC/SCElectionResults.xml
```

A cached snippet from 2013 showed this as an RSS feed listing elections with their URLs:
```
2013 U.S. House District 1 Special Election
http://www.enr-scvotes.org/SC/46180/index.htm
```

This may be the source for building a historical backfill of election EIDs.

---

## 8. Known Election EIDs (Observed)

Collected from research — these are confirmed working URLs:

| Election (approx) | Scope | EID | Full URL Fragment |
|---|---|---|---|
| 2024 General | State | 125820 | `/SC/125820/web.345435/` |
| 2024 General | Charleston | 119138 | `/SC/Charleston/119138/web.317647/` |
| 2024 General | State (alt?) | 119816 | `/SC/119816/web.317647/` |
| 2022 General (approx) | State | 115412 | `/SC/115412/Web02-state.307150/` |
| 2022 Primary (approx) | State | 114143 | `/SC/114143/Web02-state.289375/` |
| 2022 Primary (approx) | State | 111639 | `/SC/111639/Web02-state.284278/` |
| 2018 General | State | 92124 | `/SC/92124/Web02-state.222648/` |
| ~2018 | State | 92124 | `/SC/92124/Web02-state.214804/` |
| ~2016 | State | 75708 | `/SC/75708/` (redirects) |
| ~2014 | State | 64658 | `/SC/64658/index.html` |
| ~2013 | State | 59148 | `/SC/59148/159444/en/summary.html` |
| ~2013 | State | 53424 | `/SC/53424/149816/en/summary.html` |
| 2013 Special | State | 46180 | `/SC/46180/index.htm` |
| ~2013 | Richland | 106542 | `/SC/Richland/106542/Web02.264677/` |
| ~2022 | Richland | 111679 | `/SC/Richland/111679/` |
| ~2022 | York | 116305 | `/SC/York/116305/` |
| ~2022 | Newberry | 102773 | `/SC/Newberry/102773/` |
| ~2022 | Abbeville | 114144 | `/SC/Abbeville/114144/` |

---

## 9. Implementation Recipe

### Polling for Active Elections (JavaScript/fetch)

```javascript
async function getSCElections() {
  const res = await fetch(
    `https://www.enr-scvotes.org/SC/elections.json?v=${Date.now()}`
  );
  const elections = await res.json(); // [] if no active election

  return elections.map(e => ({
    name: e.ElectionName,
    date: e.Date.split(' ')[0],       // strip time → "MM/DD/YYYY"
    year: e.Date.split('/')[2].split(' ')[0],
    scope: e.County ? 'county' : 'state',
    county: e.County || null,
    eid: e.EID,
    url: e.County
      ? `https://www.enr-scvotes.org/SC/${e.County.replace(/ /g, '_')}/${e.EID}/`
      : `https://www.enr-scvotes.org/SC/${e.EID}/`
  }));
}
```

### Django Model Suggestion

```python
class SCElection(models.Model):
    election_name = models.CharField(max_length=200)
    election_date = models.DateField()
    scope = models.CharField(max_length=10, choices=[('state','State'),('county','County')])
    county = models.CharField(max_length=100, blank=True, null=True)
    eid = models.IntegerField(unique=False)  # not globally unique — same name, diff county
    enr_url = models.URLField()
    discovered_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = [('eid', 'county')]
```

---

## 10. Key Takeaways

1. **`elections.json` is the canonical discovery API.** No scraping needed. No auth.
2. **EID is the only ID you need** — the `web.XXXXXX` segment is resolved by the server automatically.
3. **CORS is fully open** — callable from browser frontends directly.
4. **The feed only shows current/active elections.** Build a polling job to capture EIDs during election seasons and persist them.
5. **For historical elections**, use `SCElectionResults.xml` or the known EID table above as a starting point.
6. **Structured data** (XML/CSV) is available at `.../reports/detailxml.zip` once you have the full resolved URL.

---

*Research conducted 2026-05-26. Based on web research, Google cache inspection, and HAR analysis of a live browser session on `www.enr-scvotes.org`.*

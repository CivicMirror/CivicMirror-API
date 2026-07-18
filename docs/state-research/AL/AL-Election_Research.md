# Alabama Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ✅ Adapter path confirmed | ENR Excel export replayable programmatically — **live-verified 2026-07-18** |

---

**Site:** https://www.sos.alabama.gov/alabama-votes/voter/election-data
**Election Night Results:** https://www2.alabamavotes.gov/electionNight/
**Operated by:** Alabama Secretary of State
**Researched:** March 4, 2026 · **HAR analysis + live verification:** July 18, 2026
**Status:** Public, no authentication required

---

## Overview

Alabama runs two separate systems:

1. **ENR (election night):** `www2.alabamavotes.gov/electionNight/` — a **custom SOS-built ASP.NET WebForms 4.0 application** (`x-aspnet-version: 4.0.30319`), Cloudflare-fronted. This is **not a vendor platform** — no Clarity/Scytl, ES&S, or KNOWiNK fingerprints. Export filename is `sosEnrExport.xlsx` and the theme path is `themes/custom/sos/`. Add to `VENDOR-Reference_Election_Tech.md` as **in-house (AL SOS)**.
2. **Certified/historical:** `www.sos.alabama.gov` — Drupal 10.6.12 serving static files (xlsx, zip, pdf) under `/sites/default/files/`.

The March assessment ("no programmatic API") was too pessimistic. There is no REST API, but the ENR export is a **stateless WebForms postback that returns a complete statewide results workbook** and is trivially scriptable.

---

## ENR System (www2.alabamavotes.gov/electionNight/)

### URL Structure

| Page | URL |
|---|---|
| Statewide results | `statewideResultsByContest.aspx?ecode={ECODE}` |
| County picker | `chooseCounty.aspx?ecode={ECODE}` |
| County results | `countyResultsByContest.aspx?cid={CID}&ecode={ECODE}` |

### Election Codes (`ecode`)

- 7-digit code; `1001295` = 2026 Primary Runoff Election (June 16, 2026).
- **Only the active election is live.** Probed `1001250–1001296`: every code except 1001295 returns an empty results shell (chrome only, no election title). Historical ENR data is purged — certified files on the Drupal site are the only historical source.
- **No election index exists.** `chooseElection.aspx`, `electionList.aspx`, `default.aspx` all 404; the site root (`/electionnight/`) is an empty ViewState-only form. The ecode must be captured per-election from wherever SOS links it (or probed). Treat as a per-election config value in the adapter.

### County ID Scheme (`cid`)

67 counties. **Non-obvious ordering:** `01`=Jefferson, `02`=Mobile, `03`=Montgomery (three largest first), then alphabetical from `04`=Autauga, `05`=Baldwin, `06`=Barbour… The `cid` URL parameter and the `County Code` column in the export use the **same scheme** (verified: all 67 match).

### Excel Export — the adapter path

The "Export Data" link is a WebForms postback, not a URL. Flow:

1. `GET statewideResultsByContest.aspx?ecode={ECODE}` → scrape hidden fields `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION`.
2. `POST` same URL, form-encoded: `__EVENTTARGET=hlnkExportData`, `__EVENTARGUMENT=` (empty), plus the three scraped fields.
3. Response: `Content-Disposition: attachment; filename=sosEnrExport.xlsx`.

Key findings from the HAR + live replay:

- **The export is always statewide.** The capture triggered it from a county page (`cid=08`, Blount) yet the file contained all 67 counties, all 50 contests (924 rows). Statewide and county exports are byte-identical — one request gets everything.
- **Stateless and unauthenticated.** Live-tested today with `requests` + a standard browser UA: fresh GET → POST worked first try, no cookies or session warmup needed. ViewState is MAC-signed but not session-bound.
- Display pagination (`cmdNext` postback, "Page 1 of 2") is irrelevant — the export bypasses it.

### Export File Format (`sosEnrExport.xlsx`)

**Sheet `AllResults`** — one row per county × contest × candidate:

| Column | Example |
|---|---|
| Election Code | 1001295 |
| Election Title | 2026 PRIMARY RUNOFF ELECTION |
| County Code | 01 |
| County Name | Jefferson |
| Contest Code | 00100892 (8-digit) |
| Contest Title | LIEUTENANT GOVERNOR (REP) |
| Candidate Number | 001 |
| Candidate Name | Wes Allen |
| Votes | 13036 |
| Party Code | REP |

Party appears both as a `(REP)`/`(DEM)` suffix in the contest title and in the Party Code column — primaries are separate contests per party.

**Sheet `Statistics`** — one row per county: Election Code, Election Title, County Code, **Ballots Cast, Total Precincts, Precincts Reported, Last Updated** (timestamp, e.g. `2026-06-16 21:59:45`). This gives per-county reporting progress for free — no HTML scraping needed for completeness tracking.

### HTML Scrape Fallback

If ever needed: contest blocks use `td.enrContestHeader`, candidate rows use `enrCandidateListItemCol` cells, election title in `span#lblElectionName`, page-level timestamp in the `LastUpdated`-classed span (`06/16/2026 10:45:53 PM`). Straight server-rendered HTML — no JS rendering, no Playwright required.

### Reference Adapter Snippet

```python
import re, requests

def fetch_al_enr_export(ecode: str) -> bytes:
    url = f"https://www2.alabamavotes.gov/electionNight/statewideResultsByContest.aspx?ecode={ecode}"
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 ..."  # standard UA sufficient
    html = s.get(url, timeout=30).text
    fields = {k: re.search(rf'id="{k}" value="([^"]+)"', html).group(1)
              for k in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")}
    r = s.post(url, data={"__EVENTTARGET": "hlnkExportData", "__EVENTARGUMENT": "", **fields}, timeout=60)
    assert "spreadsheetml" in r.headers.get("Content-Type", "")
    return r.content  # sosEnrExport.xlsx — sheets: AllResults, Statistics
```

Parse with pandas/openpyxl; `Statistics.Precincts Reported == Total Precincts` per county is the completeness signal.

---

## Certified / Historical Results (sos.alabama.gov, Drupal)

### Precinct-Level Archives

`/alabama-votes/voter/election-data` links ~128 data files:

- **Precinct results ZIPs** per election back to at least 2012, e.g. `/sites/default/files/election-data/2026-07/2026 Alabama Republican Party Primary Runoff Precinct Results.zip`, `.../2024-12/2024-General Precinct Level Results.zip`.
- **ALVR voter-registration workbooks** annually (`ALVR-2026.xlsx` … `ALVR-2012.xls`).
- Turnout/demographic summaries for some cycles (2018 by race/age/gender).

URL pattern is `/sites/default/files/election-data/{YYYY-MM}/{human-named-file}` — the month bucket is the *upload* month, not the election month, and filenames are inconsistent (spaces, underscores, `_0`/`_1` dedupe suffixes). **File discovery must scrape the election-data page HTML**; URL construction from naming patterns is not reliable.

⚠️ ZIP internal format not verified this session — the sandbox couldn't reach sos.alabama.gov (egress proxy TLS failure; the site also disallows robots). Download one locally and confirm the per-precinct schema before building the certified adapter.

### Per-Year Certification Files

`/alabama-votes/voter/election-information/{year}` (e.g. `/2026`) links certification xlsx/pdf per election under `/sites/default/files/election-{year}/`:

- `2026 Democratic Primary Runoff Election Results.xlsx`, `2026 Democratic Primary Election Results.xlsx` — statewide certified totals.
- `HouseDistrict-63-SpecialGeneralElection-UnofficialResults.xlsx` — special election format sample (from HAR): one sheet per county, title row, then columns **PARTY | CONTEST | CANDIDATE | TOTALVOTES**. Simple but has a merged title row and no county column — county comes from the sheet name.
- Party certifications and State Canvassing Board certifications are PDF only.

Same caveat: no stable naming; scrape the year page.

---

## Adapter Design Recommendation

- **Election night (live):** deterministic adapter polling the ENR export postback. One request returns the full statewide picture including reporting progress. Suggest ≥60s polling interval; the Statistics sheet's per-county `Last Updated` timestamps let you skip unchanged counties downstream. Fits the hybrid architecture as a structured-source adapter, keyed by ecode (manual config per election).
- **Certified (post-election):** xlsx ingestion from the Drupal year pages, with HTML-scrape discovery. Two format families so far: the ENR-style export schema and the simpler PARTY/CONTEST/CANDIDATE/TOTALVOTES per-county-sheet layout.
- **Precinct-level:** ZIP archives fill the sub-county granularity ENR lacks — verify format, then decide deterministic vs. LLM pipeline.

## Open Questions

- No AUP/terms found on the ENR site (cf. Kentucky, where AUP confirmation was required before using live ENR). Nothing prohibitive observed, but worth a look before election-night polling at scale.
- ecode discovery per election — check on the next election night whether SOS's homepage or election-information page links the live ecode, or whether it stays bookmark-only.
- Precinct ZIP internal schema (blocked from sandbox; verify locally).
- Whether ENR serves partial results identically mid-count (capture was post-certification; 100% precincts reported).

---

## Source Coverage Analysis

Alabama's state sources now cover Stage 2 well: live county-level results with reporting progress via the ENR export, certified totals via Drupal xlsx, and precinct-level archives back a decade. Remaining gaps vs. CivicMirror requirements are unchanged from March: ballot measure text, candidate contact/biographical data, incumbent status, and district boundaries (GeoJSON/FIPS) are absent from state files. Fill with **Google Civic API** (officials, districts, ballot measures by address), **Ballotpedia** (candidate profiles, measure text), **OpenStates** (state legislative), and **MEDSL** (historical normalization).

# Kentucky Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ✅ Path identified | Certified results via **OpenElections** (CSV) / elect.ky.gov downloads. Live ENR (Clarity + KY-SOS `vrsws`) ruled out — both Akamai-gated, `vrsws` explicitly prohibits scraping. |

---

**Primary source:** https://elect.ky.gov/results/
**Operated by:** Kentucky State Board of Elections / Secretary of State
**Researched:** March 4, 2026
**Updated:** May 31, 2026 — ENR systems identified, results-ingestion path resolved
**Status:** Public, no authentication required (bulk/certified data); live ENR is bot-protected

---

## Overview

Kentucky publishes election results through the State Board of Elections (SBE) and Secretary of State. There are three distinct layers:

1. **Bulk / certified results** — downloadable files and PDFs on `elect.ky.gov`, and standardized CSVs via the third-party OpenElections project. *This is the layer CivicMirror should use.*
2. **Live election-night reporting (ENR)** — two separate web systems, both behind Akamai bot protection (details below). Not suitable for automated ingestion.
3. **Campaign finance** — Registry of Election Finance (out of scope for results).

---

## Election Night Reporting (ENR) — Two Systems

Kentucky runs **two** ENR front-ends. Both are Akamai-protected and unsuitable for scraping.

### 1. Clarity (vendor system)
- **Host:** `https://results.enr.clarityelections.com/KY/`
- **Vendor:** SOE Software / Civix ("Clarity"), Florida-based
- **Structure:**
  - Election manifest: `https://results.enr.clarityelections.com/KY/elections.json` (lists EIDs)
  - Election page: `/KY/{EID}/{subpage}/en/summary.html`
  - Modern SPA form: `/KY/{EID}/web.{VER}/#/summary`
  - **Structured downloads:** `/KY/{EID}/{subpage}/reports/detailxml.zip` (also CSV, XLS) — the *intended* bulk-data mechanism
  - State file aggregates county-level results; each county has its own subpage with precinct-level data. County subpage URLs involve redirects and are not predictable — require scraping.
- **Block:** Akamai Bot Manager. Plain/server-side requests from datacenter IPs return **403** (IP reputation + TLS fingerprint + JS challenge). Vendor-wide, not KY-specific.
- **Tooling (if ever needed):**
  - `clarify` (`pip install clarify`, openelections/ghing) — discovers zip URLs, parses detail XML into Python objects. Does **not** download/unzip — leaves that to the caller.
  - `washingtonpost/elex-clarity` — CLI for pulling Clarity results.
  - `courierjournal/clarity-elections-finder` — EID discovery via `elections.json` and EID-incrementing.
  - ⚠️ Several Clarity-parsing repos in search results are 2020 election-fraud-conspiracy projects — avoid as references; use the maintained tools above.

### 2. Kentucky SOS ENR (state-built)
- **Host:** `https://vrsws.sos.ky.gov/liveresults/`
  - Statewide: `/liveresults/Statewide`
  - County map: `/liveresults/CountyMap`
- **What it is:** Kentucky's own "Election Night Reporting" portal. Currently serving the **2026 Primary (May 19, 2026)** — full contest list across statewide / county / precinct levels, 120 counties, 3,189 precincts. Has a client-side auto-refresh timer (implies a backend data/JSON feed).
- **Block — IMPORTANT:** Returns **403** served as a *"Kentucky State Board of Elections — Acceptable Use Policy"* page. The notice explicitly states the SBE firewall has identified website scraping ("bot") activity from the requesting IP and that they strictly limit this activity for security/stability. Response carries an `akamai-grn` header (Akamai-backed). A browser-style user-agent slips through, **but doing so is exactly what the AUP prohibits** — automated/scheduled requests risk getting the server IP firewalled.
- **Verdict:** Do **not** ingest from this host programmatically. Off-limits on policy grounds.

---

## Recommended Path for CivicMirror (Stage 2)

CivicMirror compares open-internet mock voting against **certified** results. Certified results are static and published in bulk, so **no live ENR scraping is required.**

### Primary: OpenElections (`openelections-data-ky`)
- **Repo:** https://github.com/openelections/openelections-data-ky (pre-processed/standardized CSVs)
- **Sources repo:** https://github.com/openelections/openelections-sources-ky (original official files — county `.xls` recap sheets, PDFs)
- **Access:** `git clone` / raw GitHub file fetch. No bot wall, nothing to circumvent. Free and permanently open.
- **Caveat:** Volunteer-driven — recent elections (e.g., 2026 primary) may lag certification by weeks/months. Track repo issues for availability.

**Schema fit (maps cleanly to the elections-vs-races model):**

Per-county precinct CSV headers:
`county, precinct, office, district, party, candidate, votes`
Optional vote-method columns: `early_voting, election_day, provisional, absentee`

Election-level spec fields:
`election_type` (primary / general / runoff / …), `result_type` (certified / unofficial / null), `special` (bool), `offices` (array)

| OpenElections | CivicMirror model |
|---|---|
| office + district | **race** |
| election record | **election** |
| `election_type` | primary vs general distinction |
| `result_type = certified` | comparison baseline |
| candidate + votes | result row |
| county / precinct | sub-jurisdiction dimension (optional) |

### Secondary / interim: elect.ky.gov official downloads
- **URL:** https://elect.ky.gov/results/
- Certified results as downloadable files and PDFs. Authoritative; use when OpenElections lags. Slower to parse (PDF/XLS), but policy-clean.


---

## 2026 Election Calendar Context (Stage 1)

- **Primary:** May 19, 2026 (confirmed on the live SOS ENR page)
- **General:** November 3, 2026
- Reference PDFs (for election-creation timing/automation):
  - Election Schedule 2026–2036: `https://elect.ky.gov/Resources/Documents/Election%20Schedule%202026-2036.pdf`
  - 2026 Election Calendar (final, 10/6/2025): `https://elect.ky.gov/Resources/Documents/2026%20Election%20Calendar%20Final%20Version%2010_6_2025.pdf`
- Wikipedia overview: `https://en.wikipedia.org/wiki/2026_Kentucky_elections`

---

## Notes

- 120 counties; 3,189 precincts (2026 primary).
- Registered voters (2026 primary): ~3,365,369.
- State Board of Elections oversees election administration; campaign finance via Registry of Election Finance.
- 2026 primary contests observed on ENR: U.S. Senator; U.S. House (all 6 districts); State Senate & State House (by district); District Judge (nonpartisan).

---

## Source Coverage Analysis

The earlier "least detailed in this batch" assessment is now resolved for results ingestion. Kentucky's two live ENR systems (Clarity vendor + the state-built `vrsws` portal) are both Akamai-gated, and the SOS portal carries an explicit anti-scraping Acceptable Use Policy — so live ENR is ruled out as an ingestion source on both technical and policy grounds. Because CivicMirror's comparison baseline is **certified** (static) data, the recommended Stage 2 source is **OpenElections** standardized CSVs (clean GitHub access, schema maps directly to elections/races/results), backed by **elect.ky.gov** official downloads for the interim period before OpenElections publishes a given cycle. **Google Civic Information API** and **Ballotpedia** remain the supplements for election/race creation, ballot measures, candidate profiles, and incumbents; **OpenStates** covers Kentucky legislative incumbents.

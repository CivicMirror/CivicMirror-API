# Iowa Election Results — Research Notes

> **Last Updated:** May 24, 2026 at 8:39 PM EDT

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | 3-year calendar PDF (annual parse); Google Civic API |
| Stage 1 — Race Creation (State/Federal) | ⚠️ Bootstrap only | SOS candidate list PDF (filing window); Google Civic API post-filing |
| Stage 1 — Race Creation (County/Local) | ⚠️ Partial | ~12+ counties use Neapolitan Labs platform with structured candidate list PDFs; upload is optional per county; 2 known 403s; no single domain pattern |
| Stage 2 — Results Ingestion | ✅ Adapter built | Clarity Elections adapter built (`results/adapters/ia.py`); needs `results_url` in admin |

---

**Site:** https://sos.iowa.gov/elections/results/index.html  
**Archived Results:** https://sos.iowa.gov/elections/results/archive.html  
**Election Calendar (PDF):** https://sos.iowa.gov/elections/pdf/cal3yr.pdf  
**Primary Election / Candidate List:** https://sos.iowa.gov/primary-election  
**Operated by:** Iowa Secretary of State  
**Researched:** March 4, 2026 (updated May 24, 2026)  
**Status:** Public, no authentication required

---

## Overview

Iowa provides election results through the Secretary of State's website. The office supervises 99 county auditors in election administration. Results include precinct-level vote totals available as Microsoft Excel files by county.

---

## Upcoming Race Ingestion Strategy

Iowa has no public race/candidate API. Ingestion requires a three-track approach covering scheduling, candidate bootstrap, and county-level gaps.

### Track 1 — Election Creation (Calendar PDF)

- **Source:** https://sos.iowa.gov/elections/pdf/cal3yr.pdf
- **Method:** Annual PDF parse (e.g. `pdfplumber`); seed the `Election` table with election dates, filing windows, and pre-registration deadlines
- **Cadence:** Once per year, or on season-start trigger
- **Notes:** Static document — not a live feed. Covers a rolling 3-year window (2025–2027 as of latest fetch). Structure is simple and parse-friendly.

**2026 Key Dates (from calendar):**

| Election | Date | Filing Window |
|---|---|---|
| Primary | June 2, 2026 | State/Federal: Feb 23–Mar 13 · County: Mar 2–Mar 20 |
| General | Nov 3, 2026 | State/Federal: Jun 27–Aug 22 · County: Aug 3–Aug 26 |

**2025/2027 City & School Elections:**

| Election | Date |
|---|---|
| City Primary 2025 | Oct 7, 2025 |
| Regular City/School 2025 | Nov 4, 2025 |
| City Runoff 2025 | Dec 2, 2025 |
| City Primary 2027 | Oct 5, 2027 |
| Regular City/School 2027 | Nov 2, 2027 |
| City Runoff 2027 | Nov 30, 2027 |

---

### Track 2 — Race Bootstrap: State & Federal (SOS Candidate List PDF)

- **Source:** https://sos.iowa.gov/primary-election (page) → links to versioned PDF, e.g.:
  - Filing window (March): `…/2026-03/2026 Primary - Candidate List Database - All Elections_14.pdf` (suffix increments with each update, e.g. `_14`)
  - Post-withdrawal final (April): `…/2026-04/2026 Primary - Candidate List Database - All Elections_1.pdf` (suffix resets to `_1` in new month folder)
- **Method:** Poll the `/primary-election` page daily during the filing window to detect the current PDF href; parse latest → extract candidate/race linkage. After filing closes, fetch the April final version for a clean deduplicated list.
- **Cadence:** Daily during filing window (Feb 23–Mar 20 for 2026 Primary); one final fetch in April after withdrawal/objection period
- **Notes:** The SOS updates this list throughout the filing period as candidates are reviewed and accepted. The April final version is structured with office, party, name, address, phone, email, and filing date — **cleaner and more complete for State/Federal races than county PDFs.** This is the pre-Civic fallback while Google Civic data is sparse.

**Offices on the 2026 Primary Ballot (hard-code race scaffolding at election creation):**

*U.S. Offices:*
- U.S. Senator
- U.S. Representative (all districts)

*State Offices:*
- Governor / Lt. Governor
- Secretary of State
- Auditor of State
- Treasurer of State
- Secretary of Agriculture
- Attorney General
- State Senator (odd-numbered districts 1–49)
- State Representative (districts 1–100)

*County Offices:*
- Some seats of County Boards of Supervisors
- County Treasurer, Recorder, Attorney
- Any vacant county offices

---

### Track 3 — Google Civic API (Post-Filing Enrichment)

Per existing coverage: Google Civic fills candidate and race data once its data is populated after the filing deadline closes. The SOS candidate list PDF (Track 2) covers the gap during the active filing window.

---

### Track 4 — County/Local Race Bootstrap (Neapolitan Labs Platform)

A vendor called **Neapolitan Labs** (Des Moines, IA) has built standalone election websites for 12+ Iowa county auditors on a shared CMS platform called **Mint Chip Lab**. These sites expose structured candidate list PDFs for local races (city, school board, county offices) not covered by the SOS list — partially closing the county race gap.

#### How It Works

Each county homepage lists upcoming/recent elections with direct links to candidate list PDFs when the county auditor has uploaded one. The PDF URL format is:

```
/files/candidates/{election_slug}_{NNNNN}.pdf
```

The numeric suffix (e.g. `98612`, `23189`) is an **opaque CMS asset ID** — not sequential, not date-derived, not predictable. It cannot be constructed. The page HTML must be scraped first to discover the href, then the PDF fetched.

**Adapter entry point:** Scrape the county homepage or `/elections/info/{election-slug}/` page → find `href` matching `/files/candidates/*.pdf` → fetch and parse PDF.

#### Confirmed County Inventory

| County | Domain | Domain Pattern | 2026 Primary Candidate List? | Accessible? |
|---|---|---|---|---|
| Benton | `elections.bentoncountyia.gov` | `elections.{county}countyia.gov` | ✅ Yes | ✅ |
| Clayton | `elections.claytoncountyia.gov` | `elections.{county}countyia.gov` | Unknown | ✅ |
| Clinton | `elections.clintoncounty-ia.gov` | `elections.{county}county-ia.gov` | Unknown | ❌ 403 |
| Des Moines | `dmcountyelections.iowa.gov` | `{abbr}countyelections.iowa.gov` | Unknown | ✅ |
| Hancock | `elections.hancockcountyia.gov` | `elections.{county}countyia.gov` | ❌ Not uploaded | ✅ |
| Jasper | `jaspercountyelections.iowa.gov` | `{county}countyelections.iowa.gov` | Unknown | ✅ |
| Marshall | `elections.marshallcountyia.gov` | `elections.{county}countyia.gov` | ❌ Not uploaded | ✅ |
| Pottawattamie | `pottcounty-ia.gov/auditor` | Embedded in county site | Unknown | ✅ |
| Scott | `elections.scottcountyiowa.gov` | Custom | Unknown | ❌ 403 |

#### Domain Patterns — No Single Rule

Three distinct URL patterns are in use across confirmed counties. There is no way to mechanically derive a county's election domain from its name alone. A lookup table must be built and maintained manually as new counties are discovered.

Known patterns:
- `elections.{county}countyia.gov` — most common (Benton, Clayton, Hancock, Marshall)
- `elections.{county}county-ia.gov` — dash variant (Clinton)
- `{county}countyelections.iowa.gov` — iowa.gov subdomain (Jasper, Des Moines)
- Custom / embedded in county site (Scott, Pottawattamie)

#### Key Constraints

- **Candidate list upload is optional.** Even confirmed Neapolitan Labs counties (Hancock, Marshall) showed no candidate list PDF for the 2026 Primary — the county auditor may not upload one at all. Do not assume a PDF exists just because the county uses the platform.
- **403 counties.** Scott and Clinton both use the platform but return HTTP 403. Likely IP/referrer blocking, not auth. May be accessible via a headless browser or different user-agent. Worth retrying.
- **Election slug URLs are predictable.** The election info page URL follows the pattern `/elections/info/{election_slug}_{YYYY_MM_DD}/` and can be constructed from known election dates — useful for targeted scraping even without a homepage link.
- **PDF content is rich.** County candidate list PDFs include name, address, phone, email, seats contested, and "vote for no more than N" — more local detail than the SOS statewide list.
- **Covers city & school board races.** The Nov 2025 Benton County PDF contained 13 municipalities plus 3 school districts with full candidate rosters — data entirely absent from any other source.

#### Recommended Scraping Approach

```
For each known Neapolitan Labs county:
  1. GET county homepage
  2. Find <a href="/files/candidates/...pdf"> in "Upcoming & Recent Elections" section
  3. If found → fetch PDF → parse candidates
  4. If not found → GET /elections/info/{constructed-slug}/
  5. Repeat step 2 on that page
  6. If still not found → county has not uploaded a list; skip or flag for manual entry
```

---

## Data Access

### Election Results & Statistics
- **URL:** https://sos.iowa.gov/iowans/election-results-statistics
- Current and recent election results
- Live results portal: https://electionresults.iowa.gov/IA/

### Precinct Vote Totals
- Precinct-by-precinct totals available by county
- Microsoft Excel format; county dropdown selector

### Archived Results
- **URL:** https://sos.iowa.gov/elections/results/archive.html
- Historical results; pre-2004 data available upon request

### Additional Data
- Voter Registration Totals
- Redistricting & Reprecincting data
- Precinct and District Shapefiles
- Maps

### Voter Registration List
- Available via request ($1,500/year for statewide list with updates)

---

## API Access

No public REST API identified. Data access is through:
1. Excel file downloads (precinct-level by county)
2. Web-based results pages (https://electionresults.iowa.gov/IA/)
3. SOS candidate list PDF (updated during filing windows)
4. 3-year election calendar PDF
5. Voter registration list (paid request)

---

## Notes

- 99 county auditors administer elections locally; no centralized county race/candidate feed exists
- Precinct-level results data available in Excel format by county
- Pre-2004 historical data available upon request
- Contact: elections@sos.iowa.gov · (515) 281-0145

---

## Source Coverage Analysis

Iowa's Secretary of State site offers precinct-level vote totals (Excel by county), archived historical results, and a live results portal at `electionresults.iowa.gov`. The 3-year calendar PDF is a reliable annual seed for election scheduling. The SOS candidate list PDF — updated throughout filing periods and finalized post-withdrawal — is the best source for State and Federal race bootstrap, with the April final version being the cleanest. County/local race ingestion is now partially addressable via the **Neapolitan Labs platform** used by 12+ Iowa county auditors: these sites expose structured candidate list PDFs covering city, school board, and county office races with rich contact data, but candidate list upload is optional per county, domain patterns are inconsistent, and two counties (Scott, Clinton) block access. The remaining ~85 counties have no structured local candidate data source identified. Geographic boundary data (Precinct and District Shapefiles) is listed as available; GeoJSON/FIPS format needs confirmation. **Google Civic Information API** and **Ballotpedia** should be used to fill candidate, ballot measure, and official gaps; **Clarity Elections** should be checked at the county level for live reporting.

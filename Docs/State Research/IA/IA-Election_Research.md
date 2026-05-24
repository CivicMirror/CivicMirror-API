# Iowa Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | 3-year calendar PDF (annual parse); Google Civic API |
| Stage 1 — Race Creation (State/Federal) | ⚠️ Bootstrap only | SOS candidate list PDF (filing window); Google Civic API post-filing |
| Stage 1 — Race Creation (County) | ❌ No centralized source | County auditor contact only; 99-county variation too fragile to scrape |
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
  `https://sos.iowa.gov/sites/default/files/2026-03/2026 Primary - Candidate List Database - All Elections_14.pdf`
- **Method:** Poll the `/primary-election` page daily during the filing window to detect PDF version bumps (the `_14` suffix increments as updates are published); parse latest PDF → extract candidate → race linkage
- **Cadence:** Daily during filing window (Feb 23–Mar 20 for 2026 Primary)
- **Notes:** The SOS updates this list throughout the filing period as candidates are reviewed and accepted by Elections Division staff. This is the pre-Civic fallback while Google Civic data is sparse.

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

### County Race Gap

- **Scott County auditor site** (`elections.scottcountyiowa.gov`) returns HTTP 403 — not viable as a data source.
- **General:** Iowa's 99 county auditor sites vary too widely in structure and accessibility to scrape reliably at scale.
- **Recommendation:** Defer county-level race creation. Rely on Google Civic post-election where available, or fall back to manual admin entry. Contact individual county auditors for missing data (`sos.iowa.gov/auditors`).

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

Iowa's Secretary of State site offers precinct-level vote totals (Excel by county), archived historical results, and a live results portal at `electionresults.iowa.gov`. The 3-year calendar PDF is a reliable annual seed for election scheduling. The SOS candidate list PDF — updated throughout filing periods — is the best available bootstrap for State and Federal race creation, but requires polling for version updates. County race ingestion has no centralized source and remains a coverage gap. Geographic boundary data (Precinct and District Shapefiles) is listed as available; GeoJSON/FIPS format needs confirmation. **Google Civic Information API** and **Ballotpedia** should be used to fill candidate, ballot measure, and official gaps; **Clarity Elections** should be checked at the county level for live reporting.

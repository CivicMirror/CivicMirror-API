# Idaho Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | Searchable DB (migration underway) — no adapter built |

---

**Site:** https://voteidaho.gov/election-results/
**Legacy Site:** https://sos.idaho.gov/elections-division/election-results/
**Operated by:** Idaho Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Idaho provides election results through VoteIdaho.gov (new platform) and the Secretary of State's legacy site. Data is available as interactive results, ZIP canvass files, Excel downloads, and PDF reports. A searchable "Canvass" database covers statewide elections from 1990–2022.

---

## Data Access

### VoteIdaho.gov (Current)
- **URL:** https://voteidaho.gov/election-results/
- Interactive maps for each race
- County-level results with dropdown selector (44 counties)
- Turnout statistics dashboard
- PDF canvass reports

### Canvass Database (Searchable)
- Statewide elections from 1990–2022
- Interactive data visualization
- County-by-county breakdown

### Download Formats
- **ZIP files:** Canvass files for each election (e.g., 2022_General_Canvass.zip)
- **Excel files:** Statewide totals by primary/general, county breakdowns
- **PDF reports:** Official canvass documents

### Legacy Archives
- **URL:** https://archive.sos.idaho.gov/ELECT/results/index.html
- Older election results with Excel and text file downloads
- Historical voter registration and turnout statistics (1980–2024)

---

## API Access

No public REST API identified. Data access is through:
1. ZIP canvass file downloads
2. Excel file downloads
3. Interactive web-based Canvass search tool
4. PDF report downloads

---

## Notes

- Results migrating from sos.idaho.gov to voteidaho.gov
- 44 counties with per-county result selection
- Canvass database is the best tool for historical lookups
- Election night reporting begins after 9 PM MST
- Local district/race results available through county election offices
---

## Source Coverage Analysis

Idaho's VoteIdaho.gov platform and legacy SOS archive provide excellent historical coverage (1990–2024) through a searchable Canvass database and downloadable ZIP/Excel files for Primary and General elections, but Special elections, ballot measures, candidate profiles, official records, and geographic boundary data are entirely absent from the state source. The platform migration from sos.idaho.gov to voteidaho.gov should be monitored for API additions. **Google Civic Information API** and **Ballotpedia** are the recommended supplementary sources for candidate data, ballot measures, and officials; **OpenFEC** covers federal candidates; and local county election offices should be checked for **Clarity Elections** live reporting.

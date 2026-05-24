# Virginia Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | JSON + GIS (own system) — no adapter built |

---

**Site:** https://www.elections.virginia.gov/resultsreports/election-results/
**Historical Database:** https://historical.elections.virginia.gov/
**Academic Database:** https://vavh.electionstats.com/
**Operated by:** Virginia Department of Elections (ELECT)
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Virginia has one of the more comprehensive election data systems in the nation. The Department of Elections provides JSON data files, CSV downloads, a searchable historical database, and GIS/map data. Results are available in multiple formats with both current and historical data access.

---

## Data Access

### Current Election Results
- **URL:** https://www.elections.virginia.gov/resultsreports/election-results/
- Results from 2005 to present
- Available as JSON files on the site
- Downloadable reports for changes to results after initial entry
- Updated in real-time during election night

### Individual Election Results CSV
- CSV download for 2005-present
- Precinct-level data

### Historical Elections Database
- **URL:** https://historical.elections.virginia.gov/
- Searchable database from 1789-present
- All from official source documents
- Inventory table showing which contests are available

### GIS/Map Data
- 2012-2018 election results available as zipped file geodatabase
- For desktop GIS users

### Virginia Public Access Project (VPAP)
- **URL:** https://www.vpap.org/
- Nonpartisan third-party data resource
- Campaign finance, election results, and political data
- Free, nonprofit

### Virginia Elections & State Elected Officials Database Project
- **URL:** https://vavh.electionstats.com/
- Academic database (UVA)
- General Assembly elections since 1949
- Gubernatorial results since 1851
- U.S. Senate elections since 1916
- U.S. House results since 1789
- Includes biographical data for ~10,000 individuals

### Voter Registration Data
- Available through Client Services
- Requires eligibility verification
- Comma-delimited text files
- Includes voter list, voting history, absentee data

---

## API Access

- **JSON data files** available directly on election results pages
- No dedicated REST API, but JSON files provide programmatic-friendly access
- CSV bulk downloads for historical data

---

## Notes

- 133 localities (95 counties + 38 independent cities)
- State Board of Elections certifies statewide results
- Local Electoral Boards certify locality results
- Odd-year election state (governor, legislature in odd years)
- Rich historical data going back to 1789
- VPAP provides excellent third-party data analysis
---

## Source Coverage Analysis

Virginia is one of the most capable state sources in the country, providing JSON result files updated every 60 seconds on election night, shapefile and geodatabase district boundaries, a searchable historical results database back to 1789, candidate filing lists, and a robust companion data layer from the Virginia Public Access Project (VPAP). Primary gaps are deep candidate biographical/contact data, platform statements, and explicit official/incumbent term-date records, which the ELECT system does not publish in bulk. These gaps can be filled using **Google Civic Information API** (candidate contact, office/term data), **Ballotpedia** (candidate bios, ballot measure classification, incumbency), **OpenStates** (Virginia General Assembly legislative data), and **OpenFEC** (federal candidate campaign finance). Virginia's own JSON real-time feed and GIS geodatabases significantly reduce reliance on external sources for results and boundaries.

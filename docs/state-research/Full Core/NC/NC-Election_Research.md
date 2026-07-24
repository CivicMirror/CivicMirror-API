# North Carolina Election Results — Research Notes

## Coverage Status

**Updated 2026-07-22 — this section was stale (dated from the original March 2026 research pass, before any NC adapter existed). Actual status:**

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Complete | `integrations/nc_sbe/tasks.py::sync_nc_elections` — lists `ENRS/` S3 folders, no Civic API dependency |
| Stage 1 — Race/Candidate Creation | ✅ Complete | `integrations/nc_sbe/tasks.py::sync_nc_candidates` — `Elections/{YEAR}/Candidate Filing/Candidate_Listing_{YEAR}.csv` on the same public S3 bucket. Scope: federal + state legislative + state executive only (judicial and county/local out of scope, same convention as KY). Primary-vs-general contests for the same office are kept distinct via `contest_variant_key` (party_contest field), mirroring VT's contest_variant pattern. |
| Stage 2 — Results Ingestion | ✅ Complete | `results/adapters/nc.py` — same S3 bucket's `ENRS/{date}/results_pct_{date}.zip` |

Full Core Coverage as of 2026-07-22 (PR #98, merged); the two new crontab entries (`sync-nc-sbe`, `sync-nc-candidates`) are active in production, scheduler reloaded same day.

**Candidate Filing CSV historical availability:** confirmed live via direct S3 listing. Naming is inconsistent before 2016 (`Candidate_listing_{YEAR}.csv` lowercase 2010–2013/2015, `Candidate_Listing_2014_rev1.csv` as an outlier); `Candidate_Listing_{YEAR}.csv` is stable from 2016 onward. The client lists the `Elections/{YEAR}/Candidate Filing/` prefix and takes whatever `.csv` key is returned rather than constructing the filename, so this doesn't need special-casing for the years CivicMirror actually syncs (2016+). No folder exists before 2010 (2010 is CivicMirror's coverage floor); 2008 has referendum PDFs only, no candidate filing; 2009 has no folder at all.

---

**Site:** https://www.ncsbe.gov/results-data
**Election Results:** https://www.ncsbe.gov/results-data/election-results
**Historical Data:** https://www.ncsbe.gov/results-data/election-results/historical-election-results-data
**How to Work with Data:** https://www.ncsbe.gov/about-elections/county-boards-elections/county-resources/county-board-kit/how-work-our-data
**Operated by:** North Carolina State Board of Elections
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

North Carolina offers one of the most comprehensive public election data systems in the country. The NC State Board of Elections proudly states they "offer more publicly available election data than almost any other state." Data includes election results, voter registration, voter history, absentee/provisional data, and GIS files, all available through their website and a public FTP site.

---

## Data Access

### Election Results Dashboard
- Live results updated every 5–10 minutes on election night
- Interactive maps, tables, and charts
- Downloadable spreadsheets
- Historical results from 1992–present

### Historical Election Results Data
- **URL:** https://www.ncsbe.gov/results-data/election-results/historical-election-results-data
- Federal, state, and local results for 20+ years
- Precinct-sorted data (with statistical noise for ballot secrecy)
- Certified results as PDF

### Public FTP Site
- Direct access to all public data files
- Voter registration data (updated weekly, Saturdays)
- Voter history data (individual-level, linkable via NCID)
- Election results files
- Absentee and provisional data

### Voter Registration Data
- **URL:** https://www.ncsbe.gov/results-data/voter-registration-data
- Current voter-level registration records
- 15+ years of historical snapshots
- Linkable to voter history via NCID or county + voter_reg_num
- Weekly Saturday updates
- Demographics: party affiliation, race, ethnicity, gender, age

### Voter History Data
- **URL:** https://www.ncsbe.gov/results-data/voter-history-data
- Individual voter participation records (10+ years)
- Group-level demographic counts (20+ years)
- Statewide and county-level files
- Includes voting method, county, precinct

### Absentee & Provisional Data
- Absentee ballot tracking files
- Provisional ballot data
- Same-day registration data

---

## API Access

No formal REST API, but the **public FTP site** provides bulk data downloads equivalent to API access. Files are well-documented with layout files and detailed instructions.

---

## Notes

- 100 counties
- Exceptionally well-documented data with "How to Work with Our Data" guide
- Precinct-sorted results include statistical noise to protect ballot secrecy
- Voter history files linkable to registration files for comprehensive analysis
- Data files updated weekly (Saturdays) for voter registration and history
- One of the best state election data systems nationwide

---

## Source Coverage Analysis

North Carolina is one of the strongest state sources in the country, providing 30+ years of precinct-level historical results, GIS/boundary files, live election night results (updated every 5–10 minutes), voter registration snapshots, and voter history data — all via a well-documented public FTP site. Primary gaps are structured ballot measure metadata (type classification), candidate contact/bio/platform information, and explicit incumbency/term data, which are not provided by the state source. These gaps can be filled using **Ballotpedia** (ballot measure type and detail, candidate bios, incumbency), **Google Civic Information API** (candidate contact info, office/term data, district lookups), **OpenStates** (NC General Assembly legislative data), and **OpenFEC** (federal candidate campaign finance). NC's own GIS files and live dashboard reduce reliance on external sources for boundary data and real-time results.

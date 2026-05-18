# Pennsylvania Election Results — Research Notes

**Site:** https://www.electionreturns.pa.gov/
**Data:** https://data.pa.gov/
**Operated by:** Pennsylvania Department of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Pennsylvania provides election results through the Department of State's election returns website and the PA Open Data portal. The state offers detailed county-level and precinct-level data.

---

## Data Access

### Election Returns
- **URL:** https://www.electionreturns.pa.gov/
- Interactive results portal
- County-level and precinct-level results
- Historical results archive

### PA Open Data Portal
- **URL:** https://data.pa.gov/
- Structured datasets with API access via Socrata/SODA
- Election-related datasets available
- CSV, JSON, and other download formats

### Download Formats
- CSV files through open data portal
- Excel files for some datasets
- PDF certified results

---

## API Access

- **Socrata/SODA API** via PA Open Data Portal for structured data queries
- No dedicated SOS REST API for election results

---

## Notes

- 67 counties
- Major swing state with high data demand
- Detailed mail-in ballot tracking data
- PA Open Data portal provides the most programmatic-friendly access
---

## Source Coverage Analysis

Pennsylvania is one of the strongest state sources in this batch, with a Socrata/SODA API via `data.pa.gov` providing programmatic access to election results, voter registration, and turnout data. However, ballot measures and judicial retention results are structurally distinct and may require separate query paths, and candidate biographical/contact data, official/incumbent records, and district boundary GeoJSON are absent from the state API. Supplement with **Google Civic Information API** (candidates, officials, district boundaries by address), **Ballotpedia** (ballot measures, candidate bios, incumbency), **OpenStates** (PA state legislative data), and **OpenFEC** (federal candidates and campaign finance). The Socrata endpoint at `data.pa.gov` is the recommended primary integration path for programmatic election result access.

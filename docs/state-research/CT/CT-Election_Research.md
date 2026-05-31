# Connecticut Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ❌ No adapter | Socrata/SODA API + EMS available; adapter not built |

---

**Site:** https://portal.ct.gov/SOTS/Election-Services/Election-Results/Election-Results
**Historical Database:** https://electionhistory.ct.gov/eng
**EMS Public Reporting:** https://ctemspublic.pcctg.net
**Open Data Portal:** https://data.ct.gov/Government/Election-Results-and-Voter-Turnout/2cta-kxuv
**Operated by:** Connecticut Secretary of the State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Connecticut provides election results through multiple channels: a historical elections database (1787–present), an Elections Management System for recent real-time results, and the CT Open Data Portal with structured datasets.

---

## Data Access

### Historical Elections Database
- **URL:** https://electionhistory.ct.gov/eng
- Coverage: State elections from 1787 to present; municipal elections from 2001 to present
- Searchable by contests, questions, candidates

### Elections Management System (EMS)
- **URL:** https://ctemspublic.pcctg.net (August 2018 to present)
- Real-time election night reporting
- Town-by-town results

### CT Open Data Portal
- **URL:** https://data.ct.gov/Government/Election-Results-and-Voter-Turnout/2cta-kxuv
- Structured dataset with API access via Socrata/SODA
- Voter turnout and results data
- Available in CSV, JSON, and other formats through the portal API

### Statement of Vote Archive
- PDF documents from 1922 to present (General Election results)
- Available through Secretary of the State's website

---

## API Access

- **Socrata/SODA API** via CT Open Data Portal for structured data queries
- No dedicated SOS REST API identified
- Historical database is HTML-based, no API

---

## Notes

- The CT Open Data Portal (data.ct.gov) provides the most programmatic-friendly access via Socrata API
- Historical depth is exceptional (1787–present)
- EMS system used for all elections since August 2018
- Municipal results available from 2001 onward in the historical database

---

## Source Coverage Analysis

Connecticut offers strong historical depth (1787–present via `electionhistory.ct.gov`) and a Socrata/SODA API via `data.ct.gov` for structured programmatic access to voter turnout and results, with real-time town-by-town reporting through the EMS system. However, the Socrata dataset's coverage of ballot measures, primaries, and special elections requires verification, and all candidate biographical data, contact information, platform statements, incumbent metadata, and district GeoJSON are absent. **Google Civic API** and **Ballotpedia** should supply candidate and official detail; **OpenStates** covers state legislative incumbents; and **MEDSL** provides normalized historical result CSVs for cross-validation. The Socrata endpoint at `data.ct.gov` is the recommended integration path for programmatic access.

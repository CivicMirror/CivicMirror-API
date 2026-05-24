# Alaska Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API; RCV elections may not map cleanly |
| Stage 2 — Results Ingestion | ❌ No adapter | No Clarity; own system |

---

**Site:** https://www.elections.alaska.gov/election-results/  
**Operated by:** Alaska Division of Elections  
**Researched:** March 4, 2026  
**Status:** Public, no authentication required

---

## Overview

Alaska provides election results through the Division of Elections website with CSV downloads, PDF reports, and JSON Cast Vote Record (CVR) files for ranked-choice voting transparency. Historical results date back to 1958.

---

## Data Access

### Election Results Portal
- **URL:** https://www.elections.alaska.gov/election-results/
- Search form for official certified results
- Results organized by election year and type

### Download Formats
- **CSV:** Results by Precinct available in CSV format
- **PDF:** Summary reports and district-level reports
- **JSON:** Cast Vote Record (CVR) files for ranked-choice voting elections

### Statistics Page
- **URL:** https://www.elections.alaska.gov/research/statistics/
- Historical statistics and data

### Historical Coverage
- Results dating back to 1958
- Precinct-level data available for recent elections

---

## Cast Vote Record (CVR) Data

Alaska publishes CVR files in JSON format for ranked-choice voting elections. These provide ballot-level data showing how each ballot ranked candidates across multiple rounds, enabling independent verification of RCV tabulation.

---

## API Access

No public REST API identified. Data access is through:
1. CSV downloads from the election results portal
2. PDF report downloads
3. JSON CVR file downloads for RCV elections
4. HTML scraping of results pages

---

## Notes

- Alaska's ranked-choice voting system means CVR data is particularly valuable
- CSV format provides precinct-level granularity
- Historical depth is excellent (back to 1958) but older data may be PDF-only

---

## Source Coverage Analysis

Alaska's Division of Elections provides excellent historical depth (results back to 1958) and uniquely valuable JSON Cast Vote Record data for RCV transparency, but the source is download-only (CSV, PDF, JSON) with no public API or real-time feed. Alaska's Top-4 Primary and Ranked-Choice General add election type complexity not well-captured in the current source. Ballot measures, candidate metadata, official/incumbent data, and geographic district boundaries are all absent from the state source. Fill these gaps with **Google Civic Information API** (candidates, districts, election type nuance), **Ballotpedia** (ballot measures, candidate bios, Alaska RCV rules), **OpenStates** (state legislative incumbents), **OpenFEC** (federal candidate data), and **MEDSL** for normalized historical results. Investigate whether Alaska uses **Clarity Elections** for election night live reporting.

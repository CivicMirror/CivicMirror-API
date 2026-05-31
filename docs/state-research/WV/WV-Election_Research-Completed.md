# West Virginia Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Complete | Google Civic API `/elections` sync; 14 races via `voterinfo` |
| Stage 1 — Race Creation | ✅ Complete | 14 races in production DB via Civic API |
| Stage 2 — Results Ingestion | ✅ Complete | Clarity Elections adapter live (`results/adapters/wv.py`) |

> **Full Coverage** — WV is the only state with all three stages fully operational.

**Site:** https://sos.wv.gov/elections/Pages/HistElecResults.aspx
**Online Results:** https://apps.sos.wv.gov/elections/results/
**Download:** https://apps.sos.wv.gov/elections/results/download.aspx
**Operated by:** West Virginia Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

West Virginia provides election results through the Secretary of State's Online Data Services portal. Results are supplied by counties and summarized at the state level. The system includes downloadable results, candidate search, and election night reporting.

---

## Data Access

### Online Election Results
- **URL:** https://apps.sos.wv.gov/elections/results/
- Results from 2008-present (online)
- County-level results
- Unofficial and official results tracking (color-coded)

### Download Election Results
- **URL:** https://apps.sos.wv.gov/elections/results/download.aspx
- Raw data download for spreadsheet or database use
- By election year

### Candidate Search
- **URL:** https://apps.sos.wv.gov/elections/candidate-search/
- Searchable by election year, level, party, and county
- Historical candidate data from 2012-present

### Historical Election Results
- **URL:** https://sos.wv.gov/elections/Pages/HistElecResults.aspx
- Pre-2008 data in West Virginia Blue Books
- Contact: Elections@wvsos.gov

### Voter Data
- Available through ElectioNet system
- Subscription service includes:
  - Monthly voter registration list updates
  - Daily updates starting 30 days before elections
  - Master voter history list after certification
  - Mail-in absentee and early voting data

### ECIE (Election Campaign & Information Entity)
- **URL:** https://apps.sos.wv.gov/elections/ecie/
- Campaign finance data

---

## API Access

No public REST API identified. Online Data Services portal provides downloadable data.

---

## Notes

- 55 counties
- Data supplied by county boards to SOS for summarization
- Results do not include write-in candidate information
- Color-coded result status: Gray=Unavailable, Yellow=Unofficial, Green=Official
- Voter data usage restricted (no commercial/charitable solicitation)
- Pre-2008 historical data in Blue Book format
---

## Source Coverage Analysis

West Virginia's SOS online portal covers election results 2008–present and provides candidate search tools (2012–present), offering better-than-average candidate name data for a state without a public API. However, ballot measure data, candidate biographical/contact details, official/incumbent records, district boundaries, and a real-time live results feed are all absent from the state source. WV is a confirmed Clarity Elections state (see `WV-Results-Adapter-Plan.md`) and the Clarity adapter is the highest-priority live data integration target for this state. Supplement remaining gaps with **Google Civic Information API** (candidates, districts, election types), **Ballotpedia** (ballot measures, candidate bios, incumbency), **OpenStates** (WV legislative data), **OpenFEC** (federal candidates), and **MEDSL** for pre-2008 historical results.

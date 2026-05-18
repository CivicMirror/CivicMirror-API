# Arkansas Election Results — Research Notes

**Site:** https://www.sos.arkansas.gov/elections  
**Results:** https://www.sos.arkansas.gov/elections/research/election-results  
**Operated by:** Arkansas Secretary of State  
**Researched:** March 4, 2026  
**Status:** Public, no authentication required

---

## Overview

Arkansas provides election results through the Secretary of State's website. The state has been transitioning election reporting vendors, which has temporarily affected availability of some results.

---

## Data Access

### Election Results Portal
- **URL:** https://www.sos.arkansas.gov/elections/research/election-results
- New election night reporting site covers 2012–2026 results
- Historical results available for older elections

### Download Formats
- **ZIP files:** Available for historical elections containing results by county and polling location
- **PDF downloads:** Historical reports
- **Historical Report of Secretary of State:** Compiled historical data

### Contact for Data
- Email: electionsemail@sos.arkansas.gov

---

## API Access

No public REST API identified. Data access is through:
1. ZIP file downloads for historical elections
2. PDF report downloads
3. Election night reporting website
4. Direct contact with Secretary of State's office

---

## Notes

- **Vendor transition in progress** — some results may be temporarily unavailable
- Historical data organized by county and polling location within ZIP downloads
- Contact email provided for data requests
- Coverage spans 2012–present on new reporting site; older data in archival formats

---

## Source Coverage Analysis

Arkansas's Secretary of State provides election results via ZIP file downloads (2012–present) and PDF archives, but coverage is limited to vote tallies by county and polling location. An ongoing vendor transition introduces reliability risk for current-cycle data, and the source entirely lacks ballot measure details, candidate biographical information, district boundary data, and incumbent metadata. **Google Civic API** and **Ballotpedia** should be used to fill candidate, official, and ballot measure gaps; **MEDSL** provides normalized historical result CSVs as a cross-reference; during the transition period, **Ballotpedia** certified result data can serve as a fallback. Direct contact with the SOS office (`electionsemail@sos.arkansas.gov`) may be necessary for custom data requests.

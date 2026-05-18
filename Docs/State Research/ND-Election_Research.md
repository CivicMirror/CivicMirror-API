# North Dakota Election Results — Research Notes

**Site:** https://vip.sos.nd.gov/electionresults.aspx
**Operated by:** North Dakota Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

North Dakota provides election results through the Secretary of State's website. North Dakota is unique in that it does not require voter registration.

---

## Data Access

### Election Results
- **URL:** https://vip.sos.nd.gov/electionresults.aspx
- County-level results
- Historical results archive
- Downloadable data files

---

## API Access

No public REST API identified.

---

## Notes

- 53 counties
- No voter registration requirement (only state without it)
- Voter ID required at polls instead

---

## Source Coverage Analysis

North Dakota's SOS website provides county-level historical results via downloadable files, but offers no API, no structured election-type metadata, no ballot measure data, and no candidate profile information. The state's unique characteristic of having no voter registration requirement (the only such state in the US) means some voter-derived supplementary data approaches used elsewhere will not apply. All gaps in candidate data, ballot measures, officials/incumbents, and district boundaries should be filled using **Google Civic Information API** (elections, candidates, district boundaries by address), **Ballotpedia** (ballot measures, candidate bios, incumbency), **OpenStates** (ND state legislative data), and **OpenFEC** (federal candidate and finance filings). Live election night results are not available from the state source and should be investigated via **Clarity Elections** or covered post-election through **MEDSL**.

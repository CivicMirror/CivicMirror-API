# New Hampshire Election Results — Research Notes

**Site:** https://www.sos.nh.gov/elections/election-results
**Operated by:** New Hampshire Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

New Hampshire provides election results through the Secretary of State's website. Results are organized by town (not county) given New Hampshire's town-meeting governance tradition.

---

## Data Access

### Election Results
- Town-level results
- Historical results archive
- Downloadable data files

---

## API Access

No public REST API identified.

---

## Notes

- 10 counties, but results organized by town/ward
- 234 towns, cities, and unincorporated places

---

## Source Coverage Analysis

New Hampshire's SOS website provides town-level historical results via downloadable files, but has no API, no structured election-type metadata, no ballot measure data, and no candidate profile information. The state's unique town/ward-based (rather than county-based) governance structure adds integration complexity, particularly for district and boundary mapping. All gaps in candidate info, ballot measures, officials/incumbents, and district boundaries should be supplemented with **Google Civic Information API** (elections, candidate info, boundary lookups by address), **Ballotpedia** (ballot measures, candidate bios, incumbency status), **OpenStates** (state legislative data), and **OpenFEC** (federal candidate and finance data). Live election night results are not available from the state source and should be investigated via **Clarity Elections** or covered post-election through **MEDSL**.

# Kentucky Election Results — Research Notes

**Site:** https://elect.ky.gov/results/
**Operated by:** Kentucky State Board of Elections / Secretary of State
**Researched:** March 4, 2026
**Status:** Public, no authentication required

---

## Overview

Kentucky provides election results through the State Board of Elections website. Results are available through an online portal and downloadable files.

---

## Data Access

### Election Results Portal
- **URL:** https://elect.ky.gov/results/
- County-level and precinct-level results
- Historical results archive

### Download Formats
- PDF reports
- Downloadable data files
- Registry of Election Finance for campaign finance data

---

## API Access

No public REST API identified. Data access is through:
1. Web-based results portal
2. PDF and data file downloads
3. County-level results pages

---

## Notes

- 120 counties in Kentucky
- State Board of Elections oversees election administration
- Campaign finance data through Registry of Election Finance
---

## Source Coverage Analysis

Kentucky's State Board of Elections portal provides county- and precinct-level historical results and a separate Registry of Election Finance for campaign data, but the state source as currently documented is the least detailed in this batch — election type enumeration, ballot measure data, candidate profiles, official/incumbent records, and geographic boundaries are all absent, and no live results feed is identified. This file should be revisited for completeness. In the interim, **Google Civic Information API** and **Ballotpedia** are the primary recommended supplements for all missing data categories; **OpenStates** covers Kentucky legislative incumbents; and **Clarity Elections** should be specifically investigated given Kentucky's 120-county structure.

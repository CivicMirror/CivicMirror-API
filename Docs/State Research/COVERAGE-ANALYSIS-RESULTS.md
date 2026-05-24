# State Election Research — Coverage Analysis Results

**Analysis date:** 2025  
**Scope:** 48 state research files reviewed against `concept.md` data requirements  
**Missing states:** TX and MA (no research files present in directory)

---

## Overview

Each of the 48 state research files in this directory was analyzed against the five core data requirements defined in `Docs/concept.md`:

1. **Elections** — Primary (Open/Closed/Non-Partisan), General, Special, Mid-Term, Party
2. **Ballot Measures** — Resolutions, Referendums (Direct & Indirect)
3. **Candidates** — Contact info, website/phone, party affiliation, CV/résumé, platform statement
4. **Officials** — Incumbent status, office held, district represented, term start/end dates
5. **Districts & Jurisdictions** — Federal/State/Local levels, geographic boundaries (GeoJSON/FIPS)

For each state, gaps in the primary state source were identified and mapped to the supplementary sources catalogued in `concept.md`. Each state file has been updated with a `## Source Coverage Analysis` section documenting its status.

---

## Summary Table

| State | Access Tier | Has API | Clarity Elections | Live Results | GIS/GeoJSON | Biggest Gap |
|---|---|---|---|---|---|---|
| **AK** | CSV/JSON downloads | ❌ | ❓ investigate | ❌ | ❌ | RCV type complexity; ballot measures |
| **AL** | Excel/Portal | ❌ | ❌ | ⚠️ portal | ❌ | Ballot measures, candidate bios |
| **AR** | ZIP downloads | ❌ | ❌ | ❌ | ❌ | Vendor transition risk; all candidate data |
| **AZ** | XML/FTP feed | ❌ | ❌ (own system) | ✅ ≤2 min | ❌ | Candidate bios, district GeoJSON |
| **CA** | REST API | ✅ | ❌ (own system) | ✅ | ❌ | Candidate contact/platform; local results |
| **CO** | Clarity + Historical DB | ❌ (Clarity) | ✅ confirmed | ✅ | ❌ | Candidate bios, incumbent metadata |
| **CT** | Socrata/SODA + EMS | ✅ (Socrata) | ❓ investigate | ✅ (EMS) | ❌ | Candidate data, ballot measure verification |
| **DE** | CSV downloads | ❌ | ❓ county level | ❌ | ❌ | Live feed; ballot measures |
| **FL** | Structured downloads | ❌ | ❌ | ❌ | ❌ | Confirm ballot measures; candidate data |
| **GA** | Data Hub + partial Clarity | ❌ | ⚠️ partial | ⚠️ | ❌ | Pre-2012 PDF-locked; ballot measures |
| **HI** | CKAN API + downloads | ✅ (CKAN) | ❓ investigate | ⚠️ batch | ❌ | Special elections; ballot measures |
| **IA** | Excel/Shapefiles | ❌ | ❓ investigate | ❌ | ⚠️ shapefiles | Live feed; candidate data |
| **ID** | Searchable DB (migration) | ❌ | ❓ county level | ❌ | ❌ | Special elections; ballot measures |
| **IL** | SBE + voter file | ❌ | ❓ county level | ❌ | ❌ | 108 authorities; ballot measures |
| **IN** | SOS archive | ❌ | ❓ county level | ❌ | ❌ | Candidate profiles; GeoJSON |
| **KS** | PDF/Excel (105 counties) | ❌ | ❓ investigate | ❌ | ❌ | Everything beyond raw results |
| **KY** | SBE portal | ❌ | ❓ investigate | ❌ | ❌ | Least-detailed file; needs revisit |
| **LA** | SOS portal (parishes) | ❌ | ❓ parish level | ❌ | ❌ | Jungle primary type; ballot measures |
| **MD** | CSV downloads | ❌ | ❓ investigate | ❌ | ❌ | Ballot measures; live feed |
| **ME** | SOS + RCV CVR | ❌ | ❌ | ❌ | ❌ | RCV complexity; ballot measures |
| **MI** | Community REST API | ✅ (community) | ❌ | ❌ | ❌ | Incumbent data; district GeoJSON |
| **MN** | GIS + real-time portal | ❌ | ❌ (own system) | ✅ | ✅ | Candidate bios; ballot measures |
| **MO** | CSV/PDF downloads | ❌ | ❌ | ❌ | ❌ | Active initiative state; ballot measures critical |
| **MS** | HTML/PDF only | ❌ | ❓ county level | ❌ | ❌ | Weakest machine-readable state |
| **MT** | PDF/CSV (limited) | ❌ | ❓ investigate | ❌ | ❌ | Active initiative state; ballot measures |
| **NC** | FTP (GIS + live) | ❌ (FTP) | ❌ (own system) | ✅ | ✅ | Candidate bios; ballot measure classification |
| **ND** | PDF/Excel downloads | ❌ | ❓ investigate | ❌ | ❌ | No voter registration; ballot measures |
| **NE** | PDF/Excel downloads | ❌ | ❓ county level | ❌ | ❌ | Nonpartisan unicameral; ballot measures |
| **NH** | Town-level downloads | ❌ | ❓ investigate | ❌ | ❌ | Town governance complexity; ballot measures |
| **NJ** | County-level downloads | ❌ | ❓ county level | ❌ | ❌ | County-clerk model; ballot measures |
| **NM** | CSV/PDF downloads | ❌ | ❓ investigate | ⚠️ unverified | ❌ | ENR platform unknown; ballot measures |
| **NV** | PDF/Excel downloads | ❌ | ❓ Clark County | ❌ | ❌ | Candidate data; live feed |
| **NY** | DB + NYENR + OpenElections | ❌ | ❌ | ✅ (NYENR) | ❌ | Candidate bios; GeoJSON (Flateau Act 2026) |
| **OH** | DATA Act + live dashboard | ❌ | ❌ (own system) | ✅ | ⚠️ | Ballot measure classification; pre-2016 data |
| **OK** | PDF/Excel downloads | ❌ | ❓ investigate | ❌ | ❌ | Thinnest documented source |
| **OR** | File downloads | ❌ | ❌ | ❌ | ❌ | Most active initiative state; ballot measures critical |
| **PA** | Socrata/SODA API | ✅ (Socrata) | ❌ | ❌ | ❌ | Ballot measure query paths; candidate data |
| **RI** | Municipal downloads | ❌ | ❌ | ❌ | ❌ | 39-municipality complexity; all gaps |
| **SC** | PDF/Excel downloads | ❌ | ❓ verify | ❌ | ❌ | Clarity status unconfirmed; all gaps |
| **SD** | Excel downloads | ❌ | ❌ | ❌ | ❌ | Active initiative state; ballot measures critical |
| **TN** | Web tables + ENR dashboard | ❌ | ❌ (own system) | ✅ | ❌ | Ballot measures; candidate data |
| **UT** | Portal + paid requests | ❌ | ❌ | ❌ | ❌ | Cost barrier; ballot measures |
| **VA** | JSON + GIS + DB (1789) | ⚠️ (JSON) | ❌ (own system) | ✅ | ✅ | Candidate contact; incumbent term dates |
| **VT** | Excel + searchable DB | ❌ | ❌ | ❌ | ❌ | Town governance complexity; incumbency |
| **WA** | Downloads + GIS files | ❌ | ❌ (own system) | ⚠️ (VBM daily) | ✅ | Most active initiative state; ballot measures critical |
| **WI** | XLSX ward-by-ward | ❌ | ❌ | ❌ | ⚠️ | Most decentralized system; no statewide live feed |
| **WV** | Portal + candidate search | ❌ | ✅ confirmed | ⚠️ status only | ❌ | Ballot measures; Clarity adapter priority |
| **WY** | PDF/Excel downloads | ❌ | ❓ investigate | ❌ | ❌ | Local data at county sites; candidate data |

---

## Cross-Cutting Findings

### 1. Candidate Biography Data Is Universally Absent
Zero of the 48 reviewed state sources provide candidate contact information, biographical data, platform statements, or website/phone details. This is a structural gap that cannot be filled from any state source. **Google Civic Information API** and **Ballotpedia** are the only viable bridges for candidate data across all states.

### 2. Ballot Measure Data Is Missing from ~40 States
The majority of state SOS sources publish ballot measure results embedded in standard result downloads but do not provide structured, typed ballot measure metadata (Referendum, Initiative, Constitutional Amendment, etc.). States with the highest urgency:
- **OR, WA, SD, MO, MT** — among the most active initiative states; ballot measure coverage is not optional
- **CA, CO** — active initiative states but better-served by API and Clarity sources
- **WV, GA, NY** — ballot measure data may exist but is not clearly documented

### 3. Real-Time / Live Results Coverage
Only ~10 states provide documented live or near-live election night results from the state source:
- **AZ** — FTP XML feed, ≤2 min updates (best in class)
- **CA** — REST API with near-real-time JSON
- **MN, NC, OH, TN, VA, NY** — live dashboards or JSON feeds
- **CO, WV** — Clarity Elections platform
- **GA** — partial Clarity; most elections on own system

For all other states, live results require either **Clarity Elections** discovery (35+ states potentially served) or post-election normalized data from **MEDSL/OpenElections**.

### 4. Clarity Elections — States to Verify
`concept.md` confirms CO and WV as Clarity Elections users. The following states should be verified on the next applicable election cycle:
- SC, IA, GA (partial), CT, MD, NM, OK, MS, NJ, KY, NV, DE, AK, NH, LA, WY, ND, NE, MT, ID, KS, IN

### 5. Geographic Boundary Data Is Sparse
Only NC, VA, MN, WA, and AZ provide clearly documented GIS/shapefile data from the state source. For all other states, district boundaries (GeoJSON/FIPS) must be sourced from:
- **Google Civic Information API** (district lookup by address)
- **U.S. Census TIGER/Line** shapefiles
- **Open Civic Data (OCD-IDs)** for division normalization

### 6. State-Specific Data Modeling Notes
These states require custom handling in the CivicMirror data model:

| State | Special Requirement |
|---|---|
| **LA** | "Jungle Primary" / top-two open primary — add `JUNGLE_PRIMARY` election subtype |
| **AK** | Top-4 Primary + RCV General — add ranked-choice ballot support |
| **ME** | RCV General elections — add ranked-choice ballot support |
| **ND** | No voter registration — voter-derived lookups not applicable |
| **VT, RI** | No county government — all districts map to town/municipality level |
| **NH** | Town/ward governance — no county election infrastructure |
| **WI** | Ward-by-ward reporting — no single live statewide feed exists |
| **NE** | Unicameral nonpartisan legislature — no party primary at legislative level |

---

## Recommended Source Prioritization

Based on coverage gaps across all 48 states:

| Priority | Source | Covers |
|---|---|---|
| **1** | Google Civic Information API | Candidates, officials, districts, election types (all states) |
| **2** | Ballotpedia | Ballot measures, candidate bios, incumbency (all states) |
| **3** | Clarity Elections (`results.enr.clarityelections.com`) | Live results (30+ states; verify per cycle) |
| **4** | OpenStates API | State legislative incumbents, bills, votes (all states) |
| **5** | OpenFEC API | Federal candidate metadata, campaign finance (all states) |
| **6** | MEDSL / Harvard Dataverse | Certified historical results, pre-API era data |
| **7** | OpenElections | State-by-state certified results (CSV, growing catalog) |
| **8** | U.S. Census TIGER/Line | District boundary shapefiles → GeoJSON conversion |

---

## Files Modified

All 48 state research files were appended with a `## Source Coverage Analysis` section:

AL, AK, AR, AZ, CA, CO, CT, DE, FL, GA, HI, IA, ID, IL, IN, KS, KY, LA, MD, ME, MI, MN, MO, MS, MT, NC, ND, NE, NH, NJ, NM, NV, NY, OH, OK, OR, PA, RI, SC, SD, TN, UT, VA, VT, WA, WI, WV, WY

**Not updated (no research files present):** TX, MA

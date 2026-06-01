# CivicMirror API

Election data aggregation and normalization platform. Ingests results from multiple public sources, normalizes them using FIPS codes and OCD-IDs, and serves a unified REST API for the [CivicMirror](https://github.com/tokendad/CivicMirror) web app.

---

## At a Glance — State Coverage

Use this table to identify the next best integration target. States with multiple ⚠️ columns and a clear public data source are the highest-value additions.

| Symbol | Meaning |
|---|---|
| ✅ | Complete — dedicated state integration working |
| ⚠️ | Partial — cross-cutting sources only (Google Civic API / OpenStates / OpenFEC) |
| ❌ | Not yet implemented |

> **Base coverage for all states via cross-cutting integrations:**
> Elections (Google Civic API) · Races (OpenStates) · Candidate Info (OpenStates — state legislative candidates, all 50 states)

---

## State Coverage

| State | Elections | Races | Community | Ballots | Live | Results | Candidate Info |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **AK** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **AL** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **AR** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **AZ** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **CA** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **CO** | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **CT** | ⚠️ | ⚠️ | ❌ | ✅ | ❌ | ✅ | ✅ |
| **DE** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **FL** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **GA** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **HI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **IA** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **ID** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **IL** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **IN** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **KS** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **KY** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **LA** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **MA** | ✅ | ✅ | ⚠️ | ✅ | ❌ | ✅ | ✅ |
| **MD** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **ME** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **MI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **MN** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **MO** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **MS** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **MT** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **NC** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **ND** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **NE** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **NH** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **NJ** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **NM** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **NV** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **NY** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **OH** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **OK** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **OR** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **PA** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **RI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **SC** | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **SD** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **TN** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **TX** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **UT** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **VA** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **VT** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **WA** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **WI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **WV** | ⚠️ | ⚠️ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **WY** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## Column Definitions

| Column | Description |
|---|---|
| **Elections** | Election metadata — date, type, jurisdiction |
| **Races** | Individual contests per election (Senator, Auditor, Clerk, etc.) |
| **Community** | Local/town/city coverage (⚠️ = select municipalities; ✅ = statewide) |
| **Ballots** | Ballot measures — referendums, initiatives, questions |
| **Live** | Live results feed during an active election night |
| **Results** | Official certified results post-election |
| **Candidate Info** | Candidate contact, images, phone, website, platform |

---

## Priority Targets

States closest to a full ✅ row based on available public data:

| State | Opportunity | Source |
|---|---|---|
| **CA** | REST API available | `https://api.sos.ca.gov` |
| **AZ** | FTP XML live feed | `ftp://ftp.azsos.gov/ElectionResults/` |
| **PA** | Socrata/SODA API | PA Open Data Portal |
| **NC** | FTP — live + GIS | NC SBE FTP site |
| **MI** | Community REST API | `michiganelections.io` |
| **MN** | Real-time portal + GIS | MN SOS |

> See [`Docs/State Research/COVERAGE-ANALYSIS-RESULTS.md`](Docs/State%20Research/COVERAGE-ANALYSIS-RESULTS.md) for the full source analysis on all 48 researched states.

---

*Last updated: 2026-06-01*

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
| **AK** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **AL** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **AR** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **AZ** | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **CA** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **CO** | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **CT** | ⚠️ | ⚠️ | ❌ | ✅ | ❌ | ✅ | ✅ |
| **DE** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **FL** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **GA** | ✅ | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ |
| **HI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **IA** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **ID** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **IL** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **IN** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **KS** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **KY** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **LA** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **MA** | ✅ | ✅ | ⚠️ | ✅ | ❌ | ✅ | ✅ |
| **MD** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **ME** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **MI** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **MN** | ⚠️ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **MO** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **MS** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **MT** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NC** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **ND** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NE** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NH** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NJ** | ⚠️ | ⚠️ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **NM** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **NV** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **NY** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **OH** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **OK** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **OR** | ✅ | ✅ | ⚠️ | ⚠️ | ❌ | ⚠️ | ✅ |
| **PA** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **RI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **SC** | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **SD** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **TN** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **TX** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **UT** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **VA** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **VT** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **WA** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **WI** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |
| **WV** | ⚠️ | ⚠️ | ❌ | ❌ | ✅ | ✅ | ✅ |
| **WY** | ⚠️ | ⚠️ | ❌ | ❌ | ❌ | ✅ | ✅ |

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
| **KY** | Add certified recap/live results ingestion to existing SOS race/candidate adapter | Kentucky SOS recaps / election-night portal |
| **TN** | Stage 1 + certified results shipped; live election-night dashboard still needs endpoint discovery | Tennessee SOS / ENR |
| **NC** | Existing adapter; Stage 1 race creation hardening | NC SBE FTP site |

> See [`docs/state-research/COVERAGE-ANALYSIS-RESULTS.md`](docs/state-research/COVERAGE-ANALYSIS-RESULTS.md) for the full source analysis on all 48 researched states.

---

*Last updated: 2026-07-15*

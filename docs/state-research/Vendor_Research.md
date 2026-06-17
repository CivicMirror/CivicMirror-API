# Vendor Reference — Election Technology Players

**Compiled:** June 16, 2026
**Context:** Cross-cutting summary of the ENR / election-data vendors identified across the CivicMirror-API state-by-state research (AZ, AR, CT, IA, KY, MA, NY, SC, WI, and others). Use this as the index when planning adapter reuse and assessing vendor-transition risk.

---

## TL;DR

- **Two companies dominate the commercial ENR space:** the incumbent **Clarity / Civix** and the challenger **KNOWiNK / BPro (TotalVote)**.
- The **KNOWiNK migration wave** (CT, AR, NE) is the biggest adapter-stability risk heading into the November 2026 cycle.
- Several states run **in-house systems** (AZ, NY, KY) and one (WI) has **no statewide results infrastructure** at all — these break the vendor-adapter pattern and need bespoke handling.

---

## Major Commercial Vendors

### 1. Clarity Elections — SOE Software / Civix (Florida)

- **Product:** "Clarity" ENR (commonly referenced as the "Clarity/Scytl" platform).
- **States / jurisdictions:**
  - **South Carolina** — current ENR (`enr-scvotes.org`).
  - **Kentucky** — legacy + parallel ENR (`results.enr.clarityelections.com/KY/`).
  - **Arkansas** — legacy only (≤2022), since migrated off.
  - **Milwaukee County, WI** — formerly; has since moved to its own portal.
- **Ingestion posture:** Akamai Bot Manager protected almost everywhere — datacenter IPs get 403'd. Generally a **scraping problem, not a clean API**. Intended bulk mechanism is `reports/detailxml.zip` (also CSV/XLS) per election.
- **Tooling:** `clarify` (pip), `washingtonpost/elex-clarity`, `courierjournal/clarity-elections-finder`. ⚠️ Avoid the 2020 election-fraud-conspiracy parsing repos that surface in search.

### 2. BPro → KNOWiNK — TotalVote / TotalResults.com

- **Maker:** **BPro, Inc.** (Pierre, South Dakota), **acquired by KNOWiNK in 2020**. Hosted on Microsoft Azure.
- **Product:** "TotalResults" is the public ENR front-end of **TotalVote**, an all-in-one election management platform (campaign finance, voter reg, results processing, ENR).
- **States / jurisdictions:**
  - **Arkansas** — **live** on the public API (`cId=arkansas`).
  - **Connecticut** — purchased KNOWiNK TotalVote to replace current EMS; **mid-transition** (risk before Nov 2026).
  - **Nebraska** — infrastructure provisioned (subdomain + TLS cert), not yet live.
  - **St. Louis, MO** (`stl`) — provisioned tenant, currently empty.
- **Ingestion posture:** **Best-case scenario.** Public, unauthenticated, multi-tenant JSON REST API at `enr-results-api.totalresults.com`, keyed by `cId`. **One adapter serves every tenant** — only the slug changes. `isOfficial` certified flag + `versionID`/`lastUpdated` for change-detection.
- **Cross-ref:** See `VENDOR-TotalResults_TotalVote.md` and `AR-Election_Research.md`.

### 3. PCC Technology Group

- **Product:** Connecticut EMS public portal (`ctemspublic.tgstg.net`, formerly `pcctg.net`).
- **States / jurisdictions:** **Connecticut** — current (being replaced by KNOWiNK TotalVote).
- **Ingestion posture:** Serves **pre-generated static JSON files**, not a REST API. Two-step version lookup → versioned directory of `*_Electiondata.json` files. Requires `curl --compressed` with explicit gzip headers to decode cleanly.

### 4. Neapolitan Labs (Des Moines, Iowa)

- **Product:** "Mint Chip Lab" CMS.
- **States / jurisdictions:** **Iowa** — 12+ counties on the elections platform; general county-government site work spans ~10 states. The standalone *elections* platform is **Iowa-only**.
- **Ingestion posture:** County-level, **not statewide**. Candidate-list PDFs live behind opaque CMS asset IDs (`/files/candidates/{slug}_{NNNNN}.pdf`) — non-sequential, must scrape page HTML to discover before fetching. Some counties Cloudflare-gated (Clinton, Clayton).

### 5. Civera

- **Product:** Backend for the SC Elections Database (`sc.elstats.civera.com`, fronting `electionhistory.scvotes.gov`).
- **States / jurisdictions:** **South Carolina** — historical results.
- **Ingestion posture:** Structured CSV endpoints (`download_search.csv`, `download_contest/{id}_table.csv`), but lags **up to a year post-certification** — **historical backfill only**, unsuitable for current-cycle results.

---

## Non-Commercial / Adjacent Data Players

| Source | Role | State |
|---|---|---|
| **Flateau Voting & Elections Database** (Dr. John L. Flateau, CUNY) | Stage 2 certified-results source | New York |
| **CivicPlus / CivicEngage** | CMS pattern behind many town election pages | Massachusetts (351 towns) |
| **AZ Citizens Clean Elections Commission** (`azcleanelections.gov`) | Candidate / race data (Stage 1), separate from results feed | Arizona |
| **OpenElections** | Sanctioned certified-data CSVs (historical) | KY, and many others |
| **MEDSL** | Normalized historical results CSVs | Multi-state |
| **Google Civic API / Ballotpedia** | Candidate bios, ballot-measure text, incumbency supplements | Multi-state |

---

## States Running In-House Systems (No Commercial Vendor)

These break the vendor-adapter pattern and require bespoke handling:

| State | System | Notes |
|---|---|---|
| **Arizona** | AZSOS HTTPS/FTP **XML feed** | Clean, unauthenticated, updates ~every 2 min on election night. State-level races only. |
| **New York** | Custom in-house ASP-style ENR (`nyenr.elections.ny.gov`) | Soft-Cloudflare; most `*.elections.ny.gov` requires Playwright stealth. Stage 1 via NYSBOE certification PDFs. |
| **Kentucky** | State-built SOS portal (`vrsws.sos.ky.gov/liveresults/`) | Runs alongside Clarity. **Explicit anti-scraping AUP** — do not automate; use OpenElections instead. |
| **Wisconsin** | WEC Drupal CMS | **No statewide results infrastructure.** Notoriously hard; results live at the county level. |

---

## Adapter-Strategy Implications

1. **Build the KNOWiNK/TotalVote adapter once, reuse everywhere.** The multi-tenant API means AR, CT, NE, and future onboarders all share one clean adapter. This is your highest-leverage build.
2. **Treat Clarity as a scraping target, not an API.** Akamai gating + AUP exposure mean Clarity states should lean on OpenElections / MEDSL for certified backfill where possible.
3. **Watch the migration wave.** CT (PCC → KNOWiNK) and the broader KNOWiNK onboarding (NE) mean adapters can change vendor under you mid-cycle. Build vendor detection into your pipeline rather than hard-coding per state.
4. **In-house states each need their own thing.** AZ (XML), NY (Playwright + cert PDFs), KY (OpenElections), WI (county-by-county) share nothing — budget per-state effort for these.
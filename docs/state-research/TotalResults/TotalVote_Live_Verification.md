# TotalVote / TotalResults — Live Verification Addendum

**Author:** live-verified follow-up to the sandboxed bot reports (`TotalResults_Research_Notes.md`, `TotalVote.md`)
**Date:** 2026-05-31
**Status:** All claims below were confirmed against the live production API (not a sandbox).

This document answers the two questions raised after the AR research:

1. **Can the AR election cycle be imported from this platform?** → **Yes. Proven with real vote data.**
2. **With the vendor known, are other states/jurisdictions connected the same way?** → **Yes. Confirmed: Montana (state, pre-launch) and St. Louis County, MO (county, live), on the same host/API.**

---

## 1. Vendor identity (resolved)

| Fact | Value |
| --- | --- |
| Product | **TotalVote** suite (Voter Registration + Campaign Finance + **ENR**) |
| ENR product listing | Microsoft AppSource `bproinc.bpro_totalvote_enr` |
| Original developer | **BPro Inc.**, Pierre, South Dakota |
| Current owner | **KNOWiNK** (St. Louis, MO) — acquired BPro in 2020–2021 |
| Public ENR host | `https://enr.totalresults.com/<deployment>` (React SPA on Azure) |
| Results API (prod) | `https://enr-results-api.totalresults.com` |
| Results API (dev) | `https://enr-dev-results-api.totalresults.com` |
| GIS layer | `https://enr-data.azureedge.us/gis/states/<state>/...` (Azure **Gov** edge) |
| Static assets | `https://enr-prod-public.s3.us-east-1.amazonaws.com` (ListBucket = AccessDenied) |

Historical BPro/TotalVote adopters (per public reporting — broader suite, not necessarily this ENR host): Hawaii (2014), New Mexico (2015), Arizona (2017), Washington (2018), Pennsylvania (2020, contract terminated), Oregon (contract terminated). A state-name `config.json` sweep did **not** find these on `enr.totalresults.com`, so their public ENR is likely self-hosted or off-platform.

---

## 2. Client identifier (`cId`) resolution — corrects the bot notes

The deployment path is **not** always the API `cId`. The SPA loads `/<deployment>/config.json` and derives the `cId` as:

```
cId = isCountyClient ? clientCountyId : clientStateId
```

Verified examples:

| Deployment path | `clientStateId` | `clientCountyId` | `isCountyClient` | **API `cId`** |
| --- | --- | --- | --- | --- |
| `/arkansas` | `arkansas` | `""` | false | `arkansas` |
| `/montana` | `montana` | `""` | false | `montana` |
| `/stl` | `missouri` | `st-louis` | true | **`st-louis`** |

This is why enumerating by state name alone is insufficient — alias paths (`stl`) and county clients are missed.

---

## 3. API contract (from the production JS bundle + HAR capture + public Swagger)

**There is a public OpenAPI spec:** `https://enr-results-api.totalresults.com/swagger/v1/swagger.json` (HTTP 200). It is the authoritative endpoint/param/schema reference. Full path list (verified live):

| Purpose | Endpoint | Required params | Notes |
| --- | --- | --- | --- |
| **Tenant config / liveness** | `Client/GetClientConfig` | `cId` | **200 = live API tenant, 204 = not configured.** The canonical way to test whether a `cId` is live (see §5). |
| Election list | `Election/GetElectionList` | `cId` | Returns `[]` for both invalid slugs *and* valid-but-empty tenants — do **not** use for liveness. |
| Election record | `Election/GetElection` | `cId`, `electionID` [`code`] | |
| Election info | `Election/GetElectionInfo` | `cId` [`electionID`, `code`] | Includes `contestTypes`, county `locations`, turnout, `versionID`/`lastUpdated`. |
| Election display config | `Election/GetElectionConfig` | `cId`, `electionID` | |
| Contest list (names) | `Contest/GetContestSearchList` | `cId` [`electionID`] | contest + choice id→name/party map. |
| **Contest results (votes)** | `Contest/GetContestResults` | `cId`, `electionID`, **`contestType`** [`locationID`, `districtID`] | |
| Single contest results | `Contest/GetSingleContestResults` | `cId`, `electionID`, `contestID` [`locationID`] | |
| Favorite/selected contests | `Contest/GetContestFavoriteResults` | `cId`, `electionID`, `contestList` | |
| Recount results | `Contest/GetContestRecountResults` | `cId`, `electionID` [`locationID`, `districtID`] | |
| **Version poll (cheap)** | `Contest/CheckCurrentVersion` | `cId`, `electionID` | Returns `versionID`/`lastUpdated`/`isOfficial` only — ideal for incremental polling. |
| Turnout | `Turnout/GetTurnout` | `cId`, `electionID` [`locationID`] | |
| **Bulk download (preferred)** | `/{clientId}/{electionId}/download` | path-style | Whole election as one JSON, **AP-style schema** (`races → reportingUnits → candidates`), with `resultsType: certified\|test`. See §4. |
| Bulk download variant | `/{clientId}/{electionId}/fullDownloadFile` | path-style | |

OpenAPI schema names are AP-style: `ApRace`, `ApCandidate`, `ApReportingUnit`, `ClientElection`, `HeaderTurnoutResponse`.

**Key correction to the bot notes:** `GetContestResults` filters by **`contestType`**, not `contestID`. Calling it with `contestID` returns `{"contests":{}}` (this is what the bots saw and mis-attributed). Valid `contestType` values come from `GetElectionInfo.response.contestTypes` — code/description pairs: `FED`/Federal, `STW`/Statewide, `SEN`, `REP`, `JUD`, `CLC`, `SCH`, `CTY`, `CIT`, `FIR`, `MEA`, `OTR`. The live HAR uses the description (`contestType=Statewide`); the code (`contestType=FED`) also returns data.

### Data join

- `GetContestSearchList` → `contestId → contestName`, `contestTypeCode`, and `choiceId → {name, partyID, color, isWriteIn}`.
- `GetContestResults` → per contest: `totalVotes`, `precinctsReporting`, `totalPrecincts`; per choice: `{choiceID, totalVotes, votePercent, isWinner}` (no names here).
- **Join `GetContestResults.choices[].choiceID` ↔ `GetContestSearchList` choice id** to attach candidate names/parties to vote totals.

### Misc
- Election ID formats: legacy numeric (`1831`–`1846`), modern GUID (post-2024 migration).
- **Change detection:** every payload carries `versionID` + `lastUpdated`. Use these as the per-election version key (analogous to Clarity's `current_ver.txt`) to skip unchanged ingests.

---

## 4. Q1 — Arkansas import proof

Chain executed live against `cId=arkansas`, electionID `1846` (2024 General):

1. `GetElectionList` → 22 elections (2012–2026). ✔
2. `GetElectionInfo` → contestTypes, county `locations`, turnout (1,190,172 ballots / 65.1%). ✔
3. `GetContestSearchList` → all contests + choice name/party map. ✔
4. `GetContestResults?contestType=FED` → contest `366` (President):
   - `759,241` (64.20%) vs `396,905` (33.56%) + 5 minor candidates.
   - Matches the real Arkansas 2024 presidential result (Trump def. Harris). ✔
5. `GetTurnout` → statewide + per-county turnout. ✔

**Conclusion:** the full AR cycle (statewide → contest → choice-level votes, winners, turnout, per-county breakdowns) is publicly retrievable and joinable. **Importable today.**

### Two ingestion paths (both verified live)

1. **Bulk `/download` — preferred for modern (GUID) elections.**
   `GET /arkansas/b412bdef-…/download` → 200, ~2.1 MB JSON, `resultsType: "certified"`, `races → reportingUnits(level=state/county/precinct) → candidates(first,last,candidateID,votes)`, precincts 2863/2863. One call = whole election, certified, AP-shaped. **Use this.**
   ⚠️ `/download` returns **404 for legacy numeric elections** (e.g. AR `1846` 2024 General). Modern GUID elections only.
2. **Granular per-contest — works for everything, incl. legacy.**
   `GetElectionInfo` (contestTypes + locations) → `GetContestSearchList` (names) → loop `GetContestResults?contestType=…` (votes) → join on `contestID`+`choiceID`. Verified on legacy `1846`. Use for pre-2024 history and for live incremental polling (pair with `CheckCurrentVersion`).

---

## 5. Q2 — Other jurisdictions on the same platform

There are **two independent "provisioning" layers**, and they must not be conflated:

- **Front-end layer** — `enr.totalresults.com/<path>/config.json` (static Azure blob). Stood up *early*, before data exists.
- **API layer** — `Client/GetClientConfig?cId=<cId>` → **200 = live tenant with data, 204 = not configured**. This is the source of truth for "can I pull results."

Authoritative roster (via `GetClientConfig`, cross-checked against front-end config + `GetElectionList`):

| Jurisdiction | Path | `cId` | Type | API `GetClientConfig` | Front-end config | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Arkansas SoS | `/arkansas` | `arkansas` | State | **200** | ✔ | **LIVE** — 22 elections 2012–2026 |
| **St. Louis County, MO** | `/stl` | **`st-louis`** | County | **200** | ✔ (`isCountyClient`) | **LIVE** — elections 2025–2026, `/download` works |
| Montana SoS | `/montana` | `montana` | State | 204 | ✔ (full SoS config) | **Pre-launch** — front-end provisioned, API not yet activated |
| Nebraska | (subdomain) | `nebraska` | State | 204 | ✗ (no path config) | **Provisioned via subdomain + TLS cert** (per vendor doc cert-transparency); not yet a live API tenant |

A **117-slug `GetClientConfig` sweep** — all 50 state names + all 50 postal abbreviations + ~17 county/city/township slugs (`st-louis`, `stlouis`, `st-charles`, `kansas-city`, `jackson`, `clay`, `greene`, `boone`, `pulaski`, `benton`, `jefferson`, `franklin`, `marion`, `douglas`, `lancaster`, …) — returned **200 for only `arkansas` and `st-louis`**; every other slug (incl. `montana`, `nebraska`, `missouri`, `connecticut`, `hawaii`, `arizona`, `washington`, `oregon`, `pennsylvania`, `newmexico`) → **204**.

**Answer:** Yes — the same vendor hosts multiple jurisdictions on one shared multi-tenant API differentiated only by `cId`, at both **state** (Arkansas) and **county** (St. Louis County) level, with more in the pipeline (Montana, Nebraska).

### ⚠️ Corrections to `VENDOR-TotalResults_TotalVote(1).md`
That doc is excellent (it surfaced the Swagger spec, `GetClientConfig` 200/204, and the `/download` endpoint), but two portfolio items are wrong because it tested the **deployment path** as the `cId`:
- It lists **`stl`** as *"provisioned, empty."* The path is `stl` but the **`cId` is `st-louis`** (county clients use `clientCountyId`). `GetClientConfig?cId=st-louis` → **200, "St. Louis Elections", live with elections**. St. Louis County is a **live** tenant, not empty.
- It does **not mention Montana**, which has a full SoS front-end config provisioned (API still 204). Montana belongs in the pre-launch column alongside Nebraska.

### Discovery vectors (for finding more)
- **Best signal:** `GetClientConfig?cId=<slug>` 200/204 sweep (authoritative; the `/config.json` and `GetElectionList` methods both have false-negatives/positives).
- `config.json` by state name found the *front-end* tenants arkansas + montana (misses alias paths like `stl` and counties).
- S3 `enr-prod-public` ListBucket → **AccessDenied** (no roster leak). GIS `enr-data.azureedge.us/gis/states/<state>/` exists per state (vector tiles, not a client list).
- **Next step:** broaden the `GetClientConfig` slug wordlist (county/city/township slugs, abbreviations) and watch cert-transparency for new `*.totalresults.com` subdomains (caught Nebraska) to auto-detect states adopting the platform.

---

## 6. CivicMirror adapter feasibility

Fits the existing `StateResultsAdapter` pattern (see `backend/results/adapters/clarity.py`):

- One generic **`TotalVoteAdapter`**; each jurisdiction = `(cId, isCountyClient)` config — same code, change only the identifier (mirrors the ClarityAdapter `state`-subclass approach).
- Map: contestType loop → `GetContestResults` → `ResultRow(office_title, candidate_name, vote_count, vote_pct, is_winner, ...)`, names joined from `GetContestSearchList`.
- Use `versionID`/`lastUpdated` for the unchanged-skip optimization (`AdapterResult(unchanged=True)`).
- Initial targets: `arkansas` (live now), `st-louis` (live now), `montana` (wire up; will populate when MT publishes).

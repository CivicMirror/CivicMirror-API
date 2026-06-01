# Vendor Profile — TotalResults.com / TotalVote (BPro / KnowInk)

**Researched:** May 31, 2026
**Context:** Identified as Arkansas's current ENR vendor (see `AR-Election_Research.md`). This doc profiles the vendor and its multi-jurisdiction footprint for CivicMirror adapter reuse.

---

## TL;DR

- **Product:** "TotalResults" is the public ENR front-end of **TotalVote**, an all-in-one election management platform.
- **Maker:** **BPro, Inc.** (Pierre, South Dakota), acquired by **KnowInk** in 2020. Hosted on Microsoft Azure.
- **API:** Public, unauthenticated, multi-tenant JSON REST API at `https://enr-results-api.totalresults.com`, keyed by `cId` (client slug). Fully documented by a public OpenAPI/Swagger spec.
- **Reusability:** Because the API is multi-tenant with a stable schema, **one CivicMirror adapter works for every `totalresults.com` client** — only the `cId` changes.
- **Current live client on this API:** **Arkansas** (`cId=arkansas`) only. **Nebraska** infrastructure is provisioned (subdomain + TLS cert) but not yet live. **`stl`** (St. Louis, MO) is a known/provisioned tenant, currently empty.
- **Broader TotalVote platform** (same BPro/KnowInk family) is reportedly used by many more states/jurisdictions (e.g., Connecticut, Missouri/St. Louis), but those may not all expose *this* `enr.totalresults.com` API.

---

## Company / Product Lineage

- **TotalVote** is a centralized platform covering online voter registration, campaign finance, electronic ballot delivery, results processing, and election-night reporting.
- Developed by **BPro** (Pierre, SD); **KnowInk** acquired BPro in **2020**.
- Cloud-hosted on **Microsoft Azure** (confirmed by `x-ms-*` / `x-azure-ref` response headers and Azure 404 placeholders on unprovisioned subdomains).
- "TotalResults.com" is the consumer-facing ENR results presentation layer of TotalVote.
- ⚠️ Much of the public writing about this vendor comes from 2020-era election-fraud-conspiracy sources. Treat their *claims* skeptically, but the *factual* lineage (BPro → KnowInk, Azure hosting, TotalVote module list, jurisdictions paying KnowInk) is corroborated across the Microsoft marketplace listing and procurement/checkbook references.

---

## API Reference (verified live)

**Base:** `https://enr-results-api.totalresults.com`
**Auth:** None for results endpoints. **Multi-tenant** via `cId` query param.
**Swagger:** `https://enr-results-api.totalresults.com/swagger/v1/swagger.json` (public, HTTP 200)
**Front-end:** `https://enr.totalresults.com/{client}` (Azure-hosted Vite/React SPA, path-based multitenancy via `azureDeploymentPath`)

### Endpoints (from OpenAPI spec)

| Method/Path | Params | Purpose |
|---|---|---|
| `GET /Client/GetClientConfig` | `cId` | Client metadata. **200 = configured client; 204 = not configured** (use this to enumerate tenants). |
| `GET /Election/GetElectionList` | `cId` | All elections: `{electionID (GUID), electionName, electionDate, isDefault}` |
| `GET /Election/GetElection` | `cId, electionID, code` | Election record |
| `GET /Election/GetElectionInfo` | `cId, electionID, code` | Metadata + turnout + `isOfficial` + `versionID`/`lastUpdated` |
| `GET /Election/GetElectionConfig` | `cId, electionID, code` | Election display config |
| `GET /Contest/GetContestSearchList` | `cId, electionID, code` | Contests + candidate choices |
| `GET /Contest/GetContestResults` | `cId, electionID, contestType, locationID, districtID, code` | Vote tallies |
| `GET /Contest/GetSingleContestResults` | `cId, electionID, contestID, locationID, code` | One contest |
| `GET /Contest/GetContestFavoriteResults` | `cId, electionID, contestList, code` | Selected contests |
| `GET /Contest/GetContestRecountResults` | `cId, electionID, locationID, districtID, code` | Recounts |
| `GET /Contest/CheckCurrentVersion` | `cId, electionID, code` | Lightweight version/poll check |
| `GET /Turnout/GetTurnout` | `cId, electionID, locationID, code` | Turnout by jurisdiction |
| **`GET /{clientId}/{electionId}/download`** | path | **Full election results, single JSON (AP-style schema). Recommended for ingestion.** |
| `GET /{clientId}/{electionId}/fullDownloadFile` | path | Full download variant |

### OpenAPI schemas
`ApCandidate`, `ApRace`, `ApReportingUnit`, `ClientElection`, `HeaderTurnoutResponse`, `Wrapper`, `ProblemDetails` — note the **`Ap*` (Associated Press-style) naming**: races, candidates, reporting units.

### Bulk download payload (verified, AR 2026 primary — ~21 MB JSON)
```
{
  "electionDate": "2026-03-03",
  "timestamp": "2026-04-29T16:34:17Z",
  "races": [
    { "officeName": "REP U.S. Senate", "numRunoff": 1,
      "resultsType": "certified",            // <-- certified flag in payload
      "reportingUnits": [
        { "statePostal": "AR", "stateName": "Arkansas",
          "reportingUnitName": "Arkansas", "level": "state",
          "lastUpdated": "...", /* candidates + votes */ } ] } ]
}
```
This single endpoint gives the whole election (races → reporting units → candidates → votes) with `resultsType: certified` — cleaner than walking the per-contest endpoints. **Prefer `/download` for CivicMirror ingestion**, fall back to the granular endpoints for live/incremental polling via `CheckCurrentVersion`.

### Client config payload (AR)
```
{ "appTitle": "ARKANSAS ELECTION NIGHT REPORTING",
  "client": "Arkansas", "clientState": "arkansas",
  "clientOrgTitle": "Arkansas Secretary of State",
  "clientLayer": "counties", "clientLayerNameKey": "CountyName",
  "clientPrecinctKey": "PPartID", "azureDeploymentPath": "/arkansas",
  "clientEnvDemo": "false", "showPrecincts": false }
```

---

## Portfolio Findings (this API)

Enumeration method: `GetClientConfig?cId={slug}` returns **200** for a configured tenant, **204** for unconfigured. (`GetElectionList` is unreliable for this — returns empty `[]` for both invalid slugs and valid-but-no-elections tenants.)

| Client (`cId`) | Status | Notes |
|---|---|---|
| `arkansas` | ✅ **Live** | Arkansas SOS. 22 elections (2026 cycle + specials). Certified data. |
| `nebraska` | 🏗️ Provisioned, not live | `nebraska.totalresults.com` subdomain + wildcard TLS cert exist (cert transparency), but Azure 404 + 204 config. **Likely onboarding.** |
| `stl` | 🏗️ Provisioned, empty | St. Louis, MO (front-end `enr.totalresults.com/stl` exists; municipal results referenced in vendor materials). |

A broad slug sweep (all 50 state names/abbreviations + common county/municipal guesses) found **no other configured tenants** on this API as of the research date. Two deployment models seen: **path-based** (`enr.totalresults.com/arkansas`) and **subdomain-based** (`*.nebraska.totalresults.com`) — Nebraska may use a separate per-state API host once live.

> Caveat: The wider **TotalVote** platform (BPro/KnowInk) serves additional jurisdictions (e.g., Connecticut, Missouri) per procurement records, but those don't necessarily surface on *this* `enr.totalresults.com` results API. The portfolio above is specifically "clients reachable via the TotalResults ENR API," not "all TotalVote customers."

---

## Implications for CivicMirror

- **Single reusable adapter.** Build one `TotalResultsAdapter(cId)` — every current/future client on this API is just a different `cId` with the identical schema and the `/download` bulk endpoint. Arkansas is the first; Nebraska likely drops in with `cId=nebraska` (or a per-state host) at zero marginal adapter cost.
- **Certified baseline built in.** `resultsType: certified` (bulk) and `isOfficial` (granular) map directly to CivicMirror's certified-comparison baseline.
- **Change detection built in.** `CheckCurrentVersion` + `versionID`/`lastUpdated` let you poll cheaply and skip unchanged data.
- **Monitoring play.** Periodically run `GetClientConfig` against candidate slugs to detect new states adopting the platform (e.g., Nebraska going live) — auto-expanding CivicMirror coverage.
- **AP-style schema** (`ApRace`/`ApCandidate`/`ApReportingUnit`) is a familiar shape and maps cleanly to election → race → choice → result, with reporting-unit levels (state/county/precinct) for sub-jurisdiction granularity.

---

## Open Questions / To Verify

- Confirm Nebraska's go-live date and whether it uses `cId=nebraska` on the shared API or a dedicated `*.nebraska.totalresults.com` host.
- Confirm full BPro/KnowInk TotalVote state list via official procurement sources (not conspiracy blogs) — useful for predicting which states CivicMirror can add via this adapter vs. need another approach.
- Verify `/download` vs `/fullDownloadFile` differences (granularity, precinct inclusion).
- Historical coverage: does the AR client retain pre-2024 elections, or only the TotalResults era? (Older AR data still via SOS ZIP/PDF + OpenElections/MEDSL.)

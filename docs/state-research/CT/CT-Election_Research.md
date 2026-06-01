# Connecticut Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | Google Civic API |
| Stage 1 — Race Creation | ⚠️ Untested | Google Civic API |
| Stage 2 — Results Ingestion | ✅ Feasible | EMS static JSON files — fully mapped; adapter buildable |

---

**EMS (Current):** https://ctemspublic.tgstg.net/#/home
**EMS (Legacy domain, pre-2025):** https://ctemspublic.pcctg.net (redirects to tgstg.net)
**Historical Database:** https://electionhistory.ct.gov/eng
**Open Data Portal:** https://data.ct.gov/Government/Election-Results-and-Voter-Turnout/2cta-kxuv
**Operated by:** Connecticut Secretary of the State (PCC Technology / tgstg.net infrastructure)
**Researched:** May 31, 2026
**Status:** Public, no authentication required

---

## Overview

Connecticut provides election results through multiple channels: the **EMS public reporting portal** at `ctemspublic.tgstg.net` (PCC Technology, used since August 2018), a historical elections database (1787–present), and the CT Open Data Portal with Socrata/SODA access. The EMS is the primary real-time results source.

**Critical context:** As of June 2024, the CT Secretary of the State has **purchased TotalVote from KNOWiNK LLC** to replace the current PCC Technology EMS. The replacement timeline is unannounced, but over $1M has been paid to KNOWiNK. The current EMS remains active (confirmed live for Nov 2025 and upcoming Nov 2026 elections). When TotalVote deploys, an adapter repoint will be needed — importantly, **TotalVote is the same vendor as Arkansas** (TotalResults.com), so the REST API patterns may be partially reusable.

---

## EMS Data Architecture — Fully Reverse-Engineered

The EMS is **not a traditional REST API**. It serves pre-generated static JSON files refreshed every 3 minutes during live elections. The AngularJS front-end fetches a versioned directory of JSON files per election. No authentication required.

### Step 1 — Election Discovery

```
GET https://ctemspublic.tgstg.net/ng-app/data/Elections.json
```

Returns an array of all elections. Each entry:

```json
{
  "ID": "97",
  "Name": "11/04/2025 -- November 2025 Municipal Election",
  "DefaultElection": "N"
}
```

**Elections span 2016 to present** (ID 1 = Nov 2016 Presidential, up to ID 108 = Nov 2026 State Election). The `DefaultElection: "Y"` flag marks the currently active/default election. Election categories (from `Lookupdata.json` `EC` field):

| EC Code | Meaning |
|---|---|
| `G` | State general / Presidential |
| `ME` | Municipal election |
| `MP` | Municipal primary |
| `TCP` | Town caucus primary |
| `TCE` | Town caucus election |

### Step 2 — Version Lookup

```
GET https://ctemspublic.tgstg.net/ng-app/data/election/{electionID}/Version.json
```

Returns: `{"Version": 70781}` — an integer version number. This changes every 3 minutes during live elections to bust the cache. All data files live under this versioned path.

### Step 3 — Static Data Files

Base path: `https://ctemspublic.tgstg.net/ng-app/data/election/{electionID}/{version}/`

| File | Content |
|---|---|
| `Lookupdata.json` | Reference data: election metadata, all towns, counties, offices, candidates, parties |
| `election_Electiondata.json` | Statewide reporting statistics (registered voters, precincts reporting, turnout %) |
| `stateVotes_Electiondata.json` | Statewide candidate vote totals by race |
| `townVotes_Electiondata.json` | Per-town candidate vote totals by race |
| `voterTurnout_Electiondata.json` | Voter turnout by town |
| `townStatus_Electiondata.json` | Reporting status per town |
| `reports_Electiondata.json` | Official/unofficial results flag (`IR`, `IO` boolean fields) |
| `districts_Electiondata.json` | District-level results (legislative, congressional) |
| `officePrecincts_Electiondata.json` | Precinct-level detail |
| `ballotQuestion_Electiondata.json` | Ballot measure results (statewide + per town) |
| `candidateGrouping_Electiondata.json` | Candidate groupings for multi-seat races |

---

## Key Schema Details

### `Lookupdata.json` structure

```
{
  "election":        { ID, NM, DT, ET, EC, P, DNM }
  "townIds":         { "1": "Andover", "2": "Ansonia", ... }   // 169 CT towns
  "counties":        { ... }
  "countyTowns":     { ... }
  "officeList":      [ { "<officeID>": { ID, NM, OT, OO, DT, D } }, ... ]
  "partyIds":        { "<partyID>": { CD, NM, P } }
  "candidateIds":    { "<candidateID>": { NM, LN, FN, MN, P, AD, CO } }
  "townParties":     { ... }
  "pollingplaceIds": { ... }
  "townPollingPlaces": { ... }
}
```

**Office type (`OT`) codes:**

| OT Code | Meaning |
|---|---|
| `SW` | Statewide |
| `PD` | Presidential |
| `C` | Congressional |
| `SM` | State municipal (local) |
| (others) | District-specific |

### `stateVotes_Electiondata.json` structure

```json
{
  "<officeID>": [
    { "<candidateID>": { "V": "5290", "TO": "55.78%" } },
    { "<candidateID>": { "V": "3826", "TO": "40.34%" } }
  ]
}
```

`V` = vote count, `TO` = vote percentage. Candidate details resolved from `candidateIds` in Lookupdata.

### `townVotes_Electiondata.json` structure

```json
{
  "<townID>": {
    "<officeID>": [
      { "<candidateID>": { "V": "1032", "TO": "49.28%" } }
    ]
  }
}
```

### `election_Electiondata.json` structure

```json
{
  "ID": "97",
  "BC": "820,703",       // ballots cast
  "PR": "669 of 669 (100%)",  // precincts reporting
  "RV": "2,253,748",    // registered voters
  "T": "168 of 168",    // towns completely reported
  "PT": "0 of 168",     // towns partially reported
  "TO": "36.42",        // turnout %
  "SVT": true
}
```

### `reports_Electiondata.json` structure

```json
{ "IR": "True", "IO": "True" }
```

`IR` = informal results published, `IO` = official (certified) results. Use `IO` to distinguish unofficial ENR from certified official results.

### `ballotQuestion_Electiondata.json` structure

```json
{
  "State Wide": [
    { "QN": "Shall the Constitution...", "YES": "843153", "NO": "610694", "NTH": "-", "NTL": "-" }
  ],
  "Andover": [
    { "QN": "...", "YES": "1047", "NO": "945", "NTH": "-", "NTL": "-" }
  ]
}
```

Full ballot question text included. Town-level breakdowns available.

---

## Election Coverage

Elections available in the EMS:

- **2016** — Nov Presidential (ID 1)
- **2017** — Nov Municipal (ID 18)
- **2018** — Nov State Election (ID 31), Aug primaries
- **2019** — Nov Municipal (ID 36), primaries, specials
- **2020** — Nov Presidential (ID 54), primaries, specials
- **2021** — Nov Municipal (ID 64), primaries, specials
- **2022** — Nov State Election (ID 80), primaries, specials
- **2023** — Nov Municipal (ID 83), primaries, specials
- **2024** — Nov Presidential (ID 91), primaries, specials
- **2025** — Nov Municipal (ID 97), primaries, specials
- **2026** — Nov State Election (ID 108) — **DefaultElection: Y** (upcoming)

Special elections and primaries are tracked separately with distinct IDs.

---

## Proposed Adapter Design

```python
CT_EMS_BASE = "https://ctemspublic.tgstg.net/ng-app/data"

def get_elections():
    return requests.get(f"{CT_EMS_BASE}/Elections.json").json()

def get_version(election_id):
    r = requests.get(f"{CT_EMS_BASE}/election/{election_id}/Version.json")
    return r.json()["Version"]

def get_results(election_id, version, filename):
    url = f"{CT_EMS_BASE}/election/{election_id}/{version}/{filename}"
    return requests.get(url).json()

# Main ingestion flow:
# 1. get_elections() → find target election by name/date
# 2. get_version(id) → get current version
# 3. get_results(id, ver, "Lookupdata.json") → build reference maps
# 4. get_results(id, ver, "stateVotes_Electiondata.json") → candidate totals
# 5. get_results(id, ver, "reports_Electiondata.json") → certification status
# 6. get_results(id, ver, "ballotQuestion_Electiondata.json") → ballot measures
# 7. get_results(id, ver, "townVotes_Electiondata.json") → sub-jurisdiction detail
```

**Data joins required:**
- `officeID` → `officeList` (race name, type)
- `candidateID` → `candidateIds` (name, party ID)
- `partyID` → `partyIds` (party abbreviation, full name)
- `townID` → `townIds` (town name)

---

## Pending Transition: TotalVote (KNOWiNK)

Connecticut has purchased **TotalVote** from KNOWiNK LLC to replace the PCC Technology EMS. Key facts:

- Purchase confirmed June 2024; over **$1M paid to KNOWiNK** (CT Open Checkbook)
- Deployment timeline: **TBD** — SOTS said "not yet determined when fully deployed"
- The current PCC/tgstg.net EMS remains live (confirmed for Nov 2025 municipal, and set as default for Nov 2026 state election)
- TotalVote's ENR module: `https://{state}.totalvote.com` (see: St. Louis, MO demo)
- **Arkansas uses the same vendor's product** (TotalResults.com) — cross-reference that adapter for API patterns when TotalVote deploys in CT

Monitor `ctemspublic.tgstg.net` vs potential `ct.totalvote.com` before the Nov 2026 state election.

---

## Additional Sources

### Historical Elections Database

- **URL:** https://electionhistory.ct.gov/eng
- Coverage: State elections from 1787 to present; municipal from 2001 to present
- HTML-only, no API — scraping required for historical data

### CT Open Data Portal (Socrata/SODA)

- **URL:** https://data.ct.gov/Government/Election-Results-and-Voter-Turnout/2cta-kxuv
- Socrata/SODA API available — good for historical cross-validation
- Dataset coverage (primaries, specials, ballot measures) requires verification

### Statement of Vote Archive

- PDF documents from 1922 to present (General Election certified results)
- Available through Secretary of the State's website

---

## Source Coverage Analysis

The CT EMS at `ctemspublic.tgstg.net` is the **recommended primary integration path**. The static JSON architecture is highly reliable (no rate limits, no auth, public CDN via Cloudflare), and the schema is fully mapped. Coverage spans all elections from Nov 2016 to present with consistent structure. Town-level, precinct-level, district-level, and ballot question results are all available in machine-readable JSON.

**Gaps:** Candidate biographical data, contact information, platform statements, incumbent metadata, and district GeoJSON are absent from the EMS — supplement from **Google Civic API**, **Ballotpedia**, and **OpenStates**. Historical data pre-2016 requires either the Socrata endpoint or the HTML historical database.

**Risk:** TotalVote transition is the primary adapter risk. Build the PCC/tgstg.net adapter now; monitor for TotalVote deployment before Nov 2026. The Arkansas TotalResults.com adapter is a useful reference for TotalVote's REST API patterns.

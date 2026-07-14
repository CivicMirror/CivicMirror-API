# Georgia Election Results — Research Notes

**Updated:** July 13, 2026  
**Primary results site:** https://results.sos.ga.gov  
**Public API root:** `https://results.sos.ga.gov/results/public/api`  
**Platform:** Enhanced Voting — Enhanced Results  
**Deployment type:** Georgia-branded custom domain using the standard Enhanced Voting application and API pattern  
**Candidate portal:** https://mvp.sos.ga.gov — Salesforce Experience Cloud

---

## Coverage Status

| Research area | Status | Best source |
|---|---:|---|
| Election discovery | ✅ Confirmed | `GET /jurisdictions/Georgia` |
| Election creation | ✅ Ready to build | `jurisdiction.elections[]` |
| Race creation | ✅ Ready to build | `GET /elections/{jurisdiction}/{electionId}/data` |
| Statewide result ingestion | ✅ Ready to build | `/data` |
| County result ingestion | ✅ Confirmed | `/data/ballot-item/{ballotItemUuid}` or media export |
| Precinct result ingestion | ✅ Confirmed | Media export or ballot-item detail |
| Historical election discovery | ✅ Confirmed | Same jurisdiction endpoint; 115 elections observed |
| Candidate filing/qualification | ⚠️ Separate system | Salesforce MVP portal with active bot checks |
| Cloud-worker access | ⚠️ Untested | Must test from the production hosting environment |

---

## Executive Findings

1. **Georgia exposes a public election-catalog endpoint.**  
   `GET /results/public/api/jurisdictions/Georgia` returned 115 elections dated from July 31, 2012 through June 16, 2026.

2. **Election IDs must be discovered, not predicted.**  
   The IDs are human-assigned and inconsistent. Examples include:

   - `06162026GeneralPrimaryRunoff`
   - `GeneralPrimary51926`
   - `March102026SpecialElection`
   - `2024NovGen`
   - `December9th2025SpecialElectoinStateHouse23and121`

   The earlier assumption that Georgia consistently uses `MMDDYYYY{ElectionType}` is incorrect.

3. **The November 2026 election slug should not be guessed.**  
   Poll the jurisdiction endpoint and use the actual `publicElectionId` when Georgia publishes it.

4. **The standard `/data` response is the best source for election metadata, races, candidates, statewide totals, and live updates.**

5. **A separate media export supplies a complete, flattened county-and-precinct dataset.**  
   The captured June 16 export was about 25.8 MB and contained all 159 counties and detailed precinct results.

6. **Georgia follows the same Enhanced Voting application pattern found in other statewide deployments.**  
   Clear state-level installations were found for Georgia, Virginia, Washington, Idaho, Utah, and Rhode Island.

7. **The Georgia MVP candidate portal is not needed for normal election/result synchronization.**  
   It is a separate Salesforce Experience Cloud application with an active bot-check configuration.

---

# 1. System Architecture

Georgia uses two distinct public systems.

## 1.1 Enhanced Voting Results System

**Host:** `results.sos.ga.gov`

This system provides:

- Public election discovery
- Election metadata
- Races and ballot options
- Statewide vote totals
- County results
- Precinct results
- Reporting metadata
- Downloadable result exports

The captured JavaScript application uses these environment values:

```text
API endpoint: /results/public/api
CDN root:     /cdn/results
Path base:    /results/public
```

The application footer identifies the product as Enhanced Voting.

## 1.2 Georgia My Voter Page

**Host:** `mvp.sos.ga.gov`

This is a Salesforce Experience Cloud application. The July 13 capture confirmed:

- Salesforce Aura requests
- `vr_MvpLandingPageController`
- `VrMvpUtility.getRecaptchaDetails`
- `Bot_Check_Active__c: true`

The newly supplied MVP capture only covered the landing page. It did **not** revalidate the previously documented candidate-search methods such as `getElectionNames`, `fetchElectionOffice`, or `fetchQualifiedCandidates`.

For CivicMirror's normal election and result workflow, the Enhanced Voting results system is sufficient.

---

# 2. Election Discovery

## Confirmed Endpoint

```http
GET https://results.sos.ga.gov/results/public/api/jurisdictions/Georgia
```

## Important Response Fields

```json
{
  "id": "Georgia",
  "name": "...",
  "shortName": "...",
  "isParent": true,
  "childLocalities": [],
  "elections": [],
  "languages": [],
  "clientTexts": {},
  "historicalElectionsUrl": null,
  "mediaExportPath": null
}
```

### Observed Counts

- **115 elections**
- **159 child localities**, corresponding to Georgia counties
- Election dates spanning **2012-07-31 through 2026-06-16**

`mediaExportPath` was null on the jurisdiction landing response. It becomes available in the election-specific `/data` response.

## 2026 Elections Observed on July 13, 2026

| Date | Election ID |
|---|---|
| 2026-01-06 | `Jan6HD23SERunoff` |
| 2026-01-20 | `January20SpecialElection` |
| 2026-02-17 | `Feb1726StateSenateDistrict18` |
| 2026-03-10 | `March102026SpecialElection` |
| 2026-04-07 | `40726SpecialElection` |
| 2026-05-12 | `51226SpecialElection` |
| 2026-05-19 | `RECOUNTPSCDistrict3` |
| 2026-05-19 | `GeneralPrimary51926` |
| 2026-06-09 | `06092026SpecialElectionRunoff` |
| 2026-06-16 | `06162026GeneralPrimaryRunoff` |

The November 3, 2026 general election was not present in the captured catalog on July 13, 2026.

## Recommended Discovery Logic

1. Request `/jurisdictions/Georgia`.
2. Iterate over `elections[]`.
3. Use the returned election date, display name, and `publicElectionId`.
4. Upsert each election.
5. Store the exact public ID in source metadata.
6. Never construct or predict the ID from the date or election type.

Suggested metadata:

```json
{
  "source_system": "enhanced_voting",
  "jurisdiction_slug": "Georgia",
  "public_election_id": "06162026GeneralPrimaryRunoff"
}
```

---

# 3. Confirmed API Endpoints

Use the exact jurisdiction and election IDs discovered from the jurisdiction endpoint.

| Purpose | Endpoint |
|---|---|
| Jurisdiction and election catalog | `GET /jurisdictions/{jurisdiction}` |
| Election metadata | `GET /elections/{jurisdiction}/{electionId}` |
| Election data and all races | `GET /elections/{jurisdiction}/{electionId}/data` |
| One race across localities | `GET /elections/{jurisdiction}/{electionId}/data/ballot-item/{ballotItemUuid}` |
| Close races | `GET /elections/{jurisdiction}/{electionId}/closeraces` |
| Localities | `GET /elections/{jurisdiction}/{electionId}/localities` |
| Statistics | `GET /elections/{jurisdiction}/{electionId}/stats` |
| Voter registration | `GET /elections/{jurisdiction}/{electionId}/vr` |
| Turnout | `GET /elections/{jurisdiction}/{electionId}/turnout` |
| Media export | `GET /cdn/results/{mediaExportPath}` |

Georgia API base:

```text
https://results.sos.ga.gov/results/public/api
```

Georgia CDN base:

```text
https://results.sos.ga.gov/cdn/results
```

No authentication was required in the supplied browser captures.

---

# 4. Election `/data` Response

## Captured Request

```http
GET /results/public/api/elections/Georgia/06162026GeneralPrimaryRunoff/data
```

## Top-Level Structure

```json
{
  "jurisdiction": {},
  "election": {},
  "localityElections": [],
  "ballotItems": [],
  "precincts": [],
  "pollingPlaces": [],
  "statistics": [],
  "voterRegistration": [],
  "voterTurnout": [],
  "ballotItemWithBreakdown": null
}
```

## Captured June 16 Runoff Data

- **27** statewide ballot items
- **159** locality election records
- Response body approximately **616 KB** in the captured HAR
- `asOf`: `2026-07-02T15:09:00.8817849Z`
- `lastUpdated`: `2026-07-02T15:08:30.0213858Z`
- Election-specific `mediaExportPath`:
  `Georgia/export-06162026GeneralPrimaryRunoff.json`

## Important Election Fields

```text
id
jurisdictionId
name[]
electionDate
isOfficialResults
isProduction
asOf
lastUpdated
publicReportCategories[]
groupReportingStatus[]
precinctReportingStatus
contestGroups[]
countGroups[]
precinctsReporting
reportingStatusBy
closeRaceThreshold
nextUpdateAt
hidePrecincts
isPrimary
parties[]
```

## Ballot Item Structure

The detailed API uses UUIDs for ballot items and ballot options.

```json
{
  "id": "ballot-item-uuid",
  "publishPublicElectionId": "06162026GeneralPrimaryRunoff",
  "name": [
    {
      "languageId": "en",
      "text": "US Senate - Rep"
    }
  ],
  "contestType": "Candidate",
  "partyName": "REP",
  "voteFor": [
    {
      "languageId": "en",
      "text": "Vote for 1"
    }
  ],
  "voteTotal": 702513,
  "reportingStatus": {
    "reportingUnits": 159,
    "totalUnits": 159
  },
  "summaryResults": {
    "ballotOptions": []
  }
}
```

## Reliability Caveats

Several aggregate fields were internally inconsistent in the captured data:

- `election.ballotItemCount` reported `1`, while `ballotItems[]` contained 27 contests.
- Method-level reporting statuses showed “Not Reported” despite complete vote totals.
- `totalVoters` and `ballotsCast` were zero despite populated results.
- The separate media export also labeled its four method reporting statuses “Not Reported.”

Therefore:

- Treat `len(ballotItems)` as the authoritative contest count.
- Use contest-level reporting units, `precinctReportingStatus`, and timestamps for progress.
- Do not infer election completeness from method-level `groupReportingStatus`.
- Do not use the captured top-level voter counts for turnout without separate validation.

---

# 5. County and Precinct Detail

Georgia exposes two practical detail paths.

## 5.1 Ballot-Item Detail Endpoint

```http
GET /elections/Georgia/{electionId}/data/ballot-item/{ballotItemUuid}
```

The captured response for one race was approximately **1.05 MB** and contained the race's county-level breakdown.

Use this when:

- Only one race needs detailed results
- A user opens a particular contest
- Frequent full precinct exports would be wasteful

## 5.2 Media Export

The `/data` response identifies the current export:

```json
{
  "jurisdiction": {
    "mediaExportPath": "Georgia/export-06162026GeneralPrimaryRunoff.json"
  }
}
```

Resulting URL:

```text
https://results.sos.ga.gov/cdn/results/Georgia/export-06162026GeneralPrimaryRunoff.json
```

## Media Export Schema

```json
{
  "electionDate": "2026-06-16",
  "electionName": "June 16th, 2026 General Primary Runoff",
  "createdAt": "2026-07-02T15:44:41.8403402Z",
  "results": {
    "id": "...",
    "name": "Georgia",
    "ballotItems": [],
    "reportingStatuses": []
  },
  "localResults": []
}
```

## Captured Export Contents

- Approximate file size: **25.8 MB**
- **27** statewide contests
- **159** county result objects
- **1,731** county-level contest records
- **3,462** county-level ballot-option records
- **56,484** precinct-option records
- **2,585** unique county/precinct combinations

The statewide totals in the supplied export matched the current `/data` response for all 27 contests.

## Recommended Usage

| Source | Best use | Advantages | Tradeoffs |
|---|---|---|---|
| `/data` | Normal polling and race creation | Smaller, richer metadata, UUIDs | Does not flatten all precinct results |
| Ballot-item detail | On-demand race drilldown | Targeted county detail | One request per contest |
| Media export | Backfill, audit, precinct import | Complete hierarchy in one object | Large download and different schema |

Recommended strategy:

1. Poll `/data` for routine synchronization.
2. Save the `mediaExportPath`.
3. Download the export only when precinct data is required, after meaningful updates, or after results become official.
4. Store the export's `createdAt` value to avoid processing the same snapshot repeatedly.

---

# 6. Identifier and Normalization Notes

## 6.1 Election IDs

Election IDs are opaque strings. Do not parse them as a guaranteed date format.

## 6.2 Contest IDs

The two data products use different identifiers:

- `/data`: UUID ballot-item identifiers
- Media export: compact IDs such as `US2R`, `S1R`, `SSD7D`

Prefer the UUID as the source contest key when available.

The compact media-export identifier should be scoped to:

```text
jurisdiction + election + contest ID
```

## 6.3 Ballot Option IDs

Media-export option IDs can repeat in different races. They must be scoped to the contest, not treated as globally unique.

## 6.4 Race Names

Examples include:

```text
US Senate - Rep
Governor - Rep
Secretary of State - Dem
State Senate - District 7/ Senador Estatal del Distrito 7 - Dem
Special State Senate - District 7/ Especial Senador Estatal del Distrito 7
```

Recommended normalization:

- Preserve the exact source name.
- Store a separately normalized display/matching name.
- Remove a final ` - Rep` or ` - Dem` only when the explicit party field agrees.
- Preserve bilingual text rather than deleting everything after `/`.
- Do not infer contest type solely from the name.
- Treat special-election contests separately from same-district primary contests.

## 6.5 Candidate Names and Party

Candidate names may include:

- Incumbency markers such as `(I)`
- Quoted nicknames
- Party text embedded in the candidate name

In the special State Senate District 7 export, candidate names included `(Rep)` and `(Dem)` while `politicalParty` was empty. Candidate cleanup should therefore support both explicit party fields and carefully parsed name suffixes.

---

# 7. Enhanced Voting Across Other States

## Statewide Deployments Found

This is a list of clear state-level public result sites found during this research. It may not be exhaustive because Enhanced Voting does not publish a complete public customer directory and some installations may not be indexed.

| State | Public host | Jurisdiction segment | Example election ID | Deployment style |
|---|---|---|---|---|
| Georgia | `results.sos.ga.gov` | `Georgia` | `06162026GeneralPrimaryRunoff` | Government custom domain |
| Virginia | `enr.elections.virginia.gov` | `virginia` | `2026-April-21-Special` | Government custom domain |
| Washington | `app.enhancedvoting.com` | `washington` | `20260428` | Vendor-hosted domain |
| Idaho | `app.enhancedvoting.com` | `id` | `nov2025` | Vendor-hosted domain |
| Utah | `electionresults.utah.gov` | `Utah` | `Primary06232026` | Government custom domain |
| Rhode Island | `electionresults.ri.gov` | `rhodeisland` | `specaug25` | Government custom domain |

## Common Public Route

Each follows this general browser route:

```text
/results/public/{jurisdiction}/elections/{electionId}
```

Examples:

```text
https://results.sos.ga.gov/results/public/Georgia/elections/06162026GeneralPrimaryRunoff
https://enr.elections.virginia.gov/results/public/virginia/elections/2026-April-21-Special
https://app.enhancedvoting.com/results/public/washington/elections/20260428
https://app.enhancedvoting.com/results/public/id/elections/nov2025
https://electionresults.utah.gov/results/public/Utah/elections/Primary06232026
https://electionresults.ri.gov/results/public/rhodeisland/elections/specaug25
```

## Shared Patterns

1. **Same application path structure**
   - `/results/public/...`
   - API convention under `/results/public/api`
   - Export files under `/cdn/results`

2. **Parent jurisdiction and child localities**
   - A state can be the parent tenant.
   - Counties or other local reporting units appear as children.

3. **Custom domains and vendor-hosted domains**
   - The application can run under a government-controlled hostname.
   - Other deployments use `app.enhancedvoting.com`.

4. **Jurisdiction identifiers are inconsistent**
   - Full names, abbreviations, and different capitalization are used.
   - Examples: `Georgia`, `virginia`, `washington`, `id`, `Utah`, `rhodeisland`.

5. **Election IDs are locally assigned**
   - Numeric dates, month abbreviations, descriptive text, and occasional misspellings all occur.
   - Discovery is mandatory.

6. **One reusable adapter is appropriate**
   - Host and jurisdiction slug should be configuration.
   - State-specific subclasses should be thin.

## Local Deployments

Search results also indicate county or municipal Enhanced Voting deployments in states including New York, Michigan, Ohio, California, Illinois, Washington, and Idaho. Those do not necessarily mean the state government uses Enhanced Voting statewide, but they reinforce that the same adapter can eventually support both state and local tenants.

---

# 8. Recommended Adapter Design

Rather than implementing Georgia as an isolated parser, use a configurable Enhanced Voting adapter.

```python
class EnhancedVotingAdapter:
    base_url: str
    jurisdiction_slug: str

    def list_elections(self):
        return self.get(f"/jurisdictions/{self.jurisdiction_slug}")

    def get_election_data(self, election_id: str):
        return self.get(
            f"/elections/{self.jurisdiction_slug}/{election_id}/data"
        )

    def get_ballot_item_detail(self, election_id: str, ballot_item_id: str):
        return self.get(
            f"/elections/{self.jurisdiction_slug}/{election_id}"
            f"/data/ballot-item/{ballot_item_id}"
        )
```

Georgia configuration:

```python
from .enhanced_voting import EnhancedVotingAdapter
from .registry import register


@register
class GeorgiaAdapter(EnhancedVotingAdapter):
    state = "GA"
    state_name = "Georgia"
    base_url = "https://results.sos.ga.gov/results/public/api"
    jurisdiction_slug = "Georgia"
```

A reusable tenant configuration could eventually replace most subclasses:

```python
ENHANCED_VOTING_TENANTS = {
    "GA": {
        "base_url": "https://results.sos.ga.gov/results/public/api",
        "jurisdiction": "Georgia",
    },
    "VA": {
        "base_url": "https://enr.elections.virginia.gov/results/public/api",
        "jurisdiction": "virginia",
    },
    "UT": {
        "base_url": "https://electionresults.utah.gov/results/public/api",
        "jurisdiction": "Utah",
    },
}
```

The Washington, Idaho, and Rhode Island API roots should be directly verified before adding them to production configuration, even though their public applications follow the same UI route pattern.

---

# 9. Proposed Georgia Synchronization Workflow

## Stage 1 — Election Discovery and Creation

1. Fetch `/jurisdictions/Georgia`.
2. Read `elections[]`.
3. Upsert election records by:
   - state
   - exact election date
   - `publicElectionId`
4. Save the exact source display name.
5. Store source metadata.
6. Optionally fetch `/data` for upcoming or active elections.
7. Seed races from `ballotItems[]`.

## Stage 2 — Result Ingestion

1. Fetch `/data`.
2. Record `asOf`, `lastUpdated`, and official status.
3. Match races by stored source UUID.
4. Update candidates and statewide totals.
5. Use contest-level reporting units.
6. Fetch ballot-item detail only when county detail is needed.
7. Fetch the media export for precinct backfills or official snapshots.
8. Preserve raw source snapshots for auditability.

## Suggested Election Metadata

```json
{
  "provider": "enhanced_voting",
  "base_url": "https://results.sos.ga.gov/results/public/api",
  "jurisdiction_slug": "Georgia",
  "public_election_id": "06162026GeneralPrimaryRunoff",
  "media_export_path": "Georgia/export-06162026GeneralPrimaryRunoff.json",
  "source_as_of": "2026-07-02T15:09:00.8817849Z",
  "source_last_updated": "2026-07-02T15:08:30.0213858Z"
}
```

---

# 10. Corrections to the Earlier Research Document

| Earlier statement | Updated finding |
|---|---|
| Election-list endpoint was not found | Confirmed at `/jurisdictions/Georgia` |
| Slugs follow `MMDDYYYY{ElectionType}` | They are inconsistent, human-assigned opaque IDs |
| November slug predicted as `11032026General` | Do not use; discover the published ID |
| Stage 1 may require manual slug entry | Election discovery can now be automated |
| Georgia is “self-hosted” | Safer description: Georgia-branded custom-domain deployment |
| MVP methods were treated as current evidence | July 13 MVP HAR only reconfirms Salesforce and active bot checks |
| `/data` was the only practical full source | Media export provides complete precinct hierarchy |
| GCP access was an open question | Still open; browser success does not prove cloud-worker access |

---

# 11. Remaining Tests Before Production

1. **Test from the actual production environment**
   - Cloud Run, worker VM, or whichever outbound IP environment will ingest results.
   - Record status code, latency, response size, and any CDN or WAF behavior.

2. **Determine publication timing**
   - Check how early a future election appears in `elections[]`.
   - Check when `/data` begins returning ballot items.

3. **Validate official-state behavior**
   - Observe `isOfficialResults`.
   - Verify winner flags and timestamps after certification.

4. **Validate export refresh behavior**
   - Compare `createdAt` with `/data.lastUpdated`.
   - Determine whether the export lags the API during election night.

5. **Verify non-Georgia API roots**
   - Confirm the jurisdiction endpoint and JSON schema directly for each Enhanced Voting state before sharing one production configuration.

6. **Add schema-drift tests**
   - Jurisdiction catalog fixture
   - Election `/data` fixture
   - Ballot-item detail fixture
   - Media export fixture
   - Special-election candidate-party edge case
   - Bilingual contest-name edge case

---

# 12. Recommended Conclusion

Georgia is ready for implementation using the shared Enhanced Voting integration.

The most important architectural change from the earlier notes is that Georgia supports fully automated election discovery. The adapter should begin at:

```http
GET /results/public/api/jurisdictions/Georgia
```

It should then use the returned election ID to request `/data`. Election IDs must be treated as opaque source identifiers rather than generated slugs.

For normal operation:

- Use `/data` for discovery, races, candidates, totals, and status.
- Use ballot-item detail for targeted county drilldowns.
- Use the media export for precinct imports, audits, and final snapshots.
- Avoid the Salesforce MVP portal unless qualification-specific candidate information is required.

---

# Evidence Reviewed

## Supplied Files

- `GA-Election_Research.md`
- `results.sos.ga.gov_Archive [26-07-13 22-20-31].har`
- `results.sos.ga.gov_Archive [26-07-13 22-21-53].har`
- `export-06162026GeneralPrimaryRunoff.json`
- `1920-Present-Voter-Turnout-History.xlsx`  
  Despite its filename and extension, this file is a JSON HAR capture of `mvp.sos.ga.gov`, not an Excel workbook.

## Public Sites Consulted

- Enhanced Voting: https://www.enhancedvoting.com/
- Georgia: https://results.sos.ga.gov/
- Virginia: https://enr.elections.virginia.gov/
- Washington and Idaho: https://app.enhancedvoting.com/
- Utah: https://electionresults.utah.gov/
- Rhode Island: https://electionresults.ri.gov/

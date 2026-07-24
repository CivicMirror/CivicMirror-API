# Georgia Election Results — Research Notes

## Coverage Status

| Stage | Status | Notes |
|---|---|---|
| Stage 1 — Election Creation | ✅ Available | results.sos.ga.gov API (slug-based) |
| Stage 1 — Race Creation | ✅ Available | ballotItems[] from /data endpoint |
| Stage 2 — Results Ingestion | ✅ Ready to build | Enhanced Voting adapter (same vendor as VA/WA) |

---

**Results Site:** https://results.sos.ga.gov
**Candidate Data Portal:** https://mvp.sos.ga.gov (Salesforce Experience Cloud)
**Operated by:** Georgia Secretary of State
**Researched:** June 29, 2026 (HAR captures from both portals)
**Platform:** Enhanced Voting (self-hosted at `results.sos.ga.gov`) — same vendor as VA ELECT and WA VoteWA

---

## Architecture

Georgia uses **two separate systems**:

1. **`results.sos.ga.gov`** — Enhanced Voting ENR platform, REST API, public, no auth
2. **`mvp.sos.ga.gov`** — Salesforce Experience Cloud portal for candidate filing/qualification (reCAPTCHA-protected)

For CivicMirror, **only `results.sos.ga.gov` is needed** (Stage 1 races + Stage 2 results both come from the same `/data` endpoint).

---

## Results API: `results.sos.ga.gov`

### Key Endpoints

| Purpose | URL |
|---|---|
| Election data (all races + totals) | `GET /results/public/api/elections/Georgia/{slug}/data` |
| Election metadata (asOf, isOfficial) | `GET /results/public/api/elections/Georgia/{slug}` |
| County breakdown for one race | `GET /results/public/api/elections/Georgia/{slug}/data/ballot-item/{ballotItemUuid}` |
| Close races | `GET /results/public/api/elections/Georgia/{slug}/closeraces` |
| XLSX download | `GET /cdn/results/{jurisdictionId}/{blobName}` |

**Authentication:** None required. All endpoints return 200 from browser (no CORS issues observed in HAR).
**GCP access:** Unknown — needs test. The existing research note ("returns 403 remotely") was based on a misidentified Clarity URL; this system is not Clarity.

### Election Slug Format

Slugs follow the pattern `MMDDYYYY{ElectionTypeShort}`:
- `06162026GeneralPrimaryRunoff` — June 16, 2026 General Primary Runoff
- `11032026General` — November 3, 2026 General (predicted)
- `12012026GeneralRunoff` — December 1, 2026 General Runoff (predicted)

The `publishPublicElectionId` field in any ballot item confirms the slug for a live election.

### 2026 Elections in results.sos.ga.gov

Confirmed from HAR (`06162026GeneralPrimaryRunoff`). Predicted slugs for November:
- `11032026General` — November 3, 2026 General Election

### Data Structure (`/data` response)

```
{
  "election": {
    "id": "uuid",
    "name": [{"languageId": "en", "text": "June 16th, 2026 General Primary Runoff"}],
    "electionDate": "2026-06-16",
    "isOfficialResults": false,
    "asOf": "2026-06-29T13:24:30.245Z",
    "lastUpdated": "2026-06-24T18:03:27.618Z",
    "isPrimary": true,
    "parties": [{"abbreviation": "REP", ...}, {"abbreviation": "DEM", ...}],
    "countGroups": [
      {"groupName": [{"text": "Election Day"}]},
      {"groupName": [{"text": "Advance Voting"}]},
      {"groupName": [{"text": "Absentee by Mail"}]},
      {"groupName": [{"text": "Provisional"}]}
    ],
    "publicReportCategories": [{
      "reports": [{"reportName": "Total Votes Excel", "blobName": "Total Votes Results_xxx.xlsx"}]
    }]
  },
  "ballotItems": [...],         // all races with vote totals
  "localityElections": [...]    // 159 counties (present in ballot-item endpoint)
}
```

### Ballot Item Structure

```json
{
  "id": "uuid",
  "publishPublicElectionId": "06162026GeneralPrimaryRunoff",
  "name": [{"languageId": "en", "text": "US Senate - Rep"}],
  "contestType": "Candidate",
  "partyName": "REP",
  "voteFor": [{"languageId": "en", "text": "Vote for 1"}],
  "voteTotal": 702504,
  "reportingStatus": {
    "reportingUnits": 159,
    "totalUnits": 159
  },
  "summaryResults": {
    "ballotOptions": [
      {
        "id": "uuid",
        "name": [{"languageId": "en", "text": "Mike Collins"}],
        "voteCount": 390167,
        "party": {"abbreviation": "REP"},
        "isWinner": null,
        "isWriteIn": false,
        "groupResults": [
          {"groupName": [{"text": "Election Day"}], "voteCount": 233881},
          {"groupName": [{"text": "Advance Voting"}],  "voteCount": 148354},
          {"groupName": [{"text": "Absentee by Mail"}], "voteCount": 7829},
          {"groupName": [{"text": "Provisional"}],     "voteCount": 103}
        ]
      }
    ]
  }
}
```

### Sample Races (June 16, 2026 General Primary Runoff)

27 ballot items, all `Candidate` type, covering:
- US Senate (Rep)
- Governor (Rep)
- Lieutenant Governor (Rep + Dem)
- Secretary of State (Rep + Dem)
- Commissioner of Insurance (Dem)
- State School Superintendent (Rep)
- Commissioner of Labor (Dem)
- PSC District 5 (Rep)
- US House Districts 1, 7, 11, 12
- State Senate Districts 7, 10, 14, 46, 51
- State House Districts 47, 58, 62, 68, 94, 117, 177

All 159 counties at 100% reporting as of HAR capture.

---

## Candidate Data Portal: `mvp.sos.ga.gov` (Salesforce / Stage 1)

The MVP portal is a Salesforce Experience Cloud app. Key Aura API methods:

| Method | Class | Purpose |
|---|---|---|
| `getElectionNames(year)` | `vrWebIntegrationController` | List elections for a year |
| `getElectionDetails(electionId)` | `vrWebIntegrationController` | Election details |
| `fetchElectionOffice(officetype, electionName, party, electionyear)` | `vrWebIntegrationController` | List offices/races |
| `fetchQualifiedCandidates(request)` | `vrWebIntegrationController` | Candidate list (**requires reCAPTCHA**) |
| `electionEndYear()` | `vrWebIntegrationController` | Latest year with elections |

**reCAPTCHA v3 gates `fetchQualifiedCandidates`** — not automatable for Stage 1.
For candidate/race creation, use the `results.sos.ga.gov/data` endpoint's `ballotItems[]` (races appear before election day; vote totals are 0 pre-election).

### 2026 Elections from MVP (Salesforce record IDs)

| Date | Name | Salesforce ID |
|---|---|---|
| 2026-12-01 | General Election Runoff | `a0pcs00000J6eO1AAJ` |
| 2026-11-03 | General Election | `a0pcs00000J6eJBAAZ` |
| 2026-07-28 | Special Election | `a0pcs00000O2pOnAAJ` |
| 2026-06-16 | General Primary Runoff | `a0pcs00000J6eCjAAJ` |
| 2026-06-09 | Special Election Runoff | `a0pcs00000NuQIjAAN` |
| 2026-05-19 | General Primary Election | `a0pcs00000J6e6HAAR` |

These IDs are **not used** by the results API (which uses date-based slugs).

---

## Implementation Plan

### Stage 2 — Results Adapter

GA is a **self-hosted Enhanced Voting instance**, identical to VA/WA in API shape. Implementation is one file — analogous to `backend/results/adapters/va.py`:

```python
# backend/results/adapters/ga.py
from .enhanced_voting import EnhancedVotingAdapter
from .registry import register

_GA_API_BASE = "https://results.sos.ga.gov/results/public/api"

@register
class GeorgiaAdapter(EnhancedVotingAdapter):
    state = "GA"
    state_name = "Georgia"
    base_url = _GA_API_BASE
```

Then set `election.source_metadata = {"enr_slug": "11032026General"}` via Django admin for the Nov 3 election.

**Critical unknown:** Does `results.sos.ga.gov` block GCP IPs? The `/data` endpoint returned 200 from the browser. Need to test with `curl` from a Cloud Run job or worker. If blocked, add to `civicmirror-proxy` ALLOWED_HOSTS (same fix used for SC and IA).

### Stage 1 — Election + Race Creation

**Option A (recommended short-term):** Manually set `enr_slug` in Django admin for known elections. Races auto-generate from `ballotItems[]` on first results fetch (same pattern as Clarity sweep states).

**Option B (future):** Build a `sync_ga_sos` task that:
1. Fetches election list from `results.sos.ga.gov` (need to confirm if there's a `/elections/Georgia` list endpoint — not yet captured in HAR)
2. Creates `Election` records with `source_metadata.enr_slug`
3. Fetches `/data` pre-election to seed races from `ballotItems[]`

### Gaps / What's Needed Before Building

1. **Test GCP access to `results.sos.ga.gov`** — curl from Cloud Run or local test
2. **Confirm November 2026 slug** — try `11032026General` once the election is configured in GA SOS system (likely available by October 2026)
3. **Find elections list endpoint** — HAR didn't capture a `/api/elections/Georgia` list; may exist at `/results/public/api/elections/Georgia` (not yet confirmed)
4. **Race name normalization** — GA names races as "US Senate - Rep" and "Governor - Rep" (party suffix); need to strip " - Rep" / " - Dem" for cross-source matching

---

## Access Notes

- `results.sos.ga.gov`: No auth. No reCAPTCHA. Browser returns all 200.
- `mvp.sos.ga.gov`: Salesforce Community, `fetchQualifiedCandidates` requires reCAPTCHA v3 token — not usable for automation.
- No Clarity ENR used. The March 2026 research note about "Partial Clarity (returns 403)" was incorrect — GA does not use Clarity.

---

## HAR Files

| File | Captured | Contents |
|---|---|---|
| `results.sos.ga.gov_Archive [26-06-29 12-37-36].har` | 2026-06-29 | June 16 runoff results + county breakdown for Governor race |
| `mvp.sos.ga.gov_Archive [26-06-29 12-35-52].har` | 2026-06-29 | Election list, election details, candidate office listing (reCAPTCHA call for candidates) |

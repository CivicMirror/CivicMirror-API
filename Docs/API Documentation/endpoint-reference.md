# CivicMirror API — Endpoint Reference

> **Version:** v1  
> **Status:** Design / Pre-implementation  
> **Base URL:** `https://api.civicmirror.io/api/v1`  
> **Last Updated:** 2026-05-17

---

## Table of Contents

1. [Introduction](#introduction)
2. [Authentication](#authentication)
3. [Quick Start](#quick-start)
4. [Common Patterns](#common-patterns)
5. [Endpoints](#endpoints)
   - [Lookup](#lookup)
   - [Elections](#elections)
   - [Races](#races)
   - [Candidates](#candidates)
   - [Ballot Measures](#ballot-measures)
   - [Officials](#officials)
   - [Districts](#districts)
6. [Data Models](#data-models)
7. [Error Handling](#error-handling)
8. [Rate Limiting](#rate-limiting)
9. [Changelog](#changelog)

---

## Introduction

The CivicMirror API aggregates and normalizes election data from multiple public sources (Google Civic, OpenStates, Ballotpedia, OpenFEC, Clarity Elections, MEDSL, and others) into a unified, queryable REST API.

All endpoints return JSON. All identifiers use [OCD-IDs](https://opencivicdata.readthedocs.io/en/latest/data/datatypes.html) and [FIPS codes](https://www.census.gov/library/reference/code-lists/ansi.html) for jurisdiction normalization. Dates are ISO 8601 (`YYYY-MM-DD` / `YYYY-MM-DDTHH:MM:SSZ`).

---

## Authentication

> **Note (Pre-development):** Authentication strategy is not finalized. The current design assumes read-only public access with optional API key for higher rate limits.

### API Key (Optional)

Pass your API key as a query parameter or header:

```
GET /api/v1/elections?key=YOUR_API_KEY
# or
Authorization: Bearer YOUR_API_KEY
```

Requests without a key are accepted but subject to stricter rate limits.

---

## Quick Start

### "What's on my ballot?"

The most common use case — given a user's address or ZIP code, return all active elections and races in their area.

```bash
curl "https://api.civicmirror.io/api/v1/lookup?address=123+Main+St+Charleston+WV+25301"
```

```json
{
  "address": {
    "formatted": "123 Main St, Charleston, WV 25301",
    "state": "WV",
    "zip": "25301"
  },
  "elections": [ ... ],
  "races": [ ... ],
  "officials": [ ... ]
}
```

### Fetch all upcoming elections in a state

```bash
curl "https://api.civicmirror.io/api/v1/elections?state=WV&status=upcoming"
```

### Fetch live results for an election

```bash
curl "https://api.civicmirror.io/api/v1/elections/wv-2024-11-05-general/results"
```

---

## Common Patterns

### Pagination

All collection endpoints (`GET /elections`, `GET /candidates`, etc.) are paginated.

**Query Parameters:**
| Param | Type | Default | Description |
|---|---|---|---|
| `page` | integer | `1` | Page number (1-indexed) |
| `page_size` | integer | `20` | Results per page (max: 100) |

**Response envelope:**
```json
{
  "count": 142,
  "next": "https://api.civicmirror.io/api/v1/elections?page=3",
  "previous": "https://api.civicmirror.io/api/v1/elections?page=1",
  "results": [ ... ]
}
```

### Filtering

Most collection endpoints support query-parameter filtering. Filters are AND-combined unless otherwise noted.

### OCD-IDs

Jurisdiction identifiers follow the Open Civic Data format:  
`ocd-division/country:us/state:wv` — West Virginia statewide  
`ocd-division/country:us/state:wv/cd:2` — WV 2nd Congressional District  
`ocd-division/country:us/state:wv/county:kanawha` — Kanawha County, WV

---

## Endpoints

---

### Lookup

The primary entry point for CivicMirror's "what's on my ballot?" user flow. Accepts an address or ZIP code and returns all relevant elections, races, and current officials for that location.

---

#### `GET /lookup`

Returns ballot and representative data for a given address or ZIP code.

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `address` | string | one of `address`/`zip` | Full street address (e.g., `123 Main St Charleston WV 25301`) |
| `zip` | string | one of `address`/`zip` | 5-digit ZIP code (e.g., `25301`). Uses representative address for the ZIP. |
| `election_id` | string | No | Scope results to a specific election |

**Success Response (200 OK):**

```json
{
  "address": {
    "formatted": "123 Main St, Charleston, WV 25301",
    "state": "WV",
    "state_fips": "54",
    "zip": "25301",
    "congressional_district": "ocd-division/country:us/state:wv/cd:2",
    "state_upper_district": "ocd-division/country:us/state:wv/sldu:9",
    "state_lower_district": "ocd-division/country:us/state:wv/sldl:36"
  },
  "elections": [
    {
      "id": "wv-2024-11-05-general",
      "name": "West Virginia General Election 2024",
      "election_date": "2024-11-05",
      "election_type": "general",
      "status": "certified"
    }
  ],
  "races": [
    {
      "id": "race_wv_2024_us_senate",
      "office_title": "U.S. Senate",
      "race_type": "candidate",
      "office_level": "federal",
      "election_id": "wv-2024-11-05-general",
      "candidates": [
        {
          "id": "cand_001",
          "name": "Jane Doe",
          "party": "Democratic",
          "party_abbr": "D",
          "incumbent": false
        }
      ]
    }
  ],
  "officials": [
    {
      "id": "off_001",
      "name": "John Smith",
      "office_title": "U.S. Senator",
      "party": "Republican",
      "term_end": "2027-01-03"
    }
  ]
}
```

**Error Responses:**

| Status | Code | Description |
|---|---|---|
| `400` | `MISSING_LOCATION` | Neither `address` nor `zip` was provided |
| `400` | `INVALID_ADDRESS` | Address could not be geocoded |
| `404` | `NO_CONTESTS` | Valid address but no active contests found (not an error condition — treat as empty ballot) |
| `503` | `UPSTREAM_UNAVAILABLE` | Google Civic API is unavailable |

**cURL:**
```bash
curl "https://api.civicmirror.io/api/v1/lookup?address=123+Main+St+Charleston+WV+25301"
```

**Python:**
```python
import requests

resp = requests.get(
    "https://api.civicmirror.io/api/v1/lookup",
    params={"address": "123 Main St Charleston WV 25301"}
)
data = resp.json()
for race in data["races"]:
    print(race["office_title"], [c["name"] for c in race["candidates"]])
```

**JavaScript:**
```javascript
const res = await fetch(
  'https://api.civicmirror.io/api/v1/lookup?address=123+Main+St+Charleston+WV+25301'
);
const data = await res.json();
data.races.forEach(race => console.log(race.office_title));
```

---

### Elections

---

#### `GET /elections`

Returns a paginated list of elections, with optional filtering.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `state` | string | 2-letter state abbreviation (e.g., `WV`) |
| `election_type` | string | `primary`, `general`, `special`, `midterm`, `party` |
| `primary_type` | string | `open`, `closed`, `nonpartisan` (only valid when `election_type=primary`) |
| `status` | string | `upcoming`, `active`, `certified` |
| `date_from` | date | ISO 8601 date — include elections on or after this date |
| `date_to` | date | ISO 8601 date — include elections on or before this date |
| `page` | integer | Page number (default: 1) |
| `page_size` | integer | Results per page (default: 20, max: 100) |

**Success Response (200 OK):**

```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "wv-2024-11-05-general",
      "name": "West Virginia General Election 2024",
      "election_date": "2024-11-05",
      "election_type": "general",
      "primary_type": null,
      "state": "WV",
      "state_fips": "54",
      "ocd_division_id": "ocd-division/country:us/state:wv",
      "status": "certified",
      "race_count": 12,
      "source": "civic_api",
      "created_at": "2024-09-01T00:00:00Z",
      "updated_at": "2024-11-20T12:00:00Z"
    }
  ]
}
```

**cURL:**
```bash
curl "https://api.civicmirror.io/api/v1/elections?state=WV&status=certified"
```

---

#### `GET /elections/{id}`

Returns a single election by ID.

**Path Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `id` | string | Election ID (e.g., `wv-2024-11-05-general`) |

**Success Response (200 OK):**

```json
{
  "id": "wv-2024-11-05-general",
  "name": "West Virginia General Election 2024",
  "election_date": "2024-11-05",
  "election_type": "general",
  "primary_type": null,
  "state": "WV",
  "state_fips": "54",
  "ocd_division_id": "ocd-division/country:us/state:wv",
  "status": "certified",
  "results_url": "https://results.enr.clarityelections.com/WV/123456/",
  "race_count": 12,
  "source": "civic_api",
  "created_at": "2024-09-01T00:00:00Z",
  "updated_at": "2024-11-20T12:00:00Z"
}
```

**Error Responses:**

| Status | Code | Description |
|---|---|---|
| `404` | `NOT_FOUND` | No election with this ID exists |

---

#### `GET /elections/{id}/races`

Returns all races (contests) associated with an election.

**Path Parameters:** `id` — Election ID

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `race_type` | string | `candidate` or `measure` |
| `office_level` | string | `federal`, `state`, `local` |
| `page` / `page_size` | integer | Pagination |

**Success Response (200 OK):**

```json
{
  "count": 12,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "race_wv_2024_us_senate",
      "election_id": "wv-2024-11-05-general",
      "office_title": "U.S. Senate",
      "race_type": "candidate",
      "office_level": "federal",
      "geography_scope": "statewide",
      "jurisdiction": "West Virginia",
      "ocd_division_id": "ocd-division/country:us/state:wv",
      "certification_status": "certified",
      "precinct_reporting": 1847,
      "total_precincts": 1847,
      "candidate_count": 3,
      "source": "civic_api",
      "created_at": "2024-09-01T00:00:00Z",
      "updated_at": "2024-11-06T08:30:00Z"
    }
  ]
}
```

---

#### `GET /elections/{id}/results`

Returns aggregate results for all races in an election. Includes both candidate races and ballot measures.

**Path Parameters:** `id` — Election ID

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `result_type` | string | `UNOFFICIAL` or `OFFICIAL` (default: latest available) |

**Success Response (200 OK):**

```json
{
  "election_id": "wv-2024-11-05-general",
  "result_type": "OFFICIAL",
  "precinct_reporting_pct": 100.0,
  "last_updated": "2024-11-20T12:00:00Z",
  "races": [
    {
      "race_id": "race_wv_2024_us_senate",
      "office_title": "U.S. Senate",
      "results": [
        {
          "candidate_id": "cand_001",
          "candidate_name": "Jane Doe",
          "party": "D",
          "vote_count": 324512,
          "vote_percentage": 52.3,
          "winner": true
        },
        {
          "candidate_id": "cand_002",
          "candidate_name": "Bob Jones",
          "party": "R",
          "vote_count": 295788,
          "vote_percentage": 47.7,
          "winner": false
        }
      ]
    }
  ]
}
```

---

### Races

---

#### `GET /races`

Returns a paginated, filterable list of races across all elections.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `state` | string | 2-letter state abbreviation |
| `election_id` | string | Filter by election |
| `race_type` | string | `candidate` or `measure` |
| `office_level` | string | `federal`, `state`, `local` |
| `office_title` | string | Partial match on office title (e.g., `Senate`) |
| `status` | string | `upcoming`, `active`, `certified` |
| `page` / `page_size` | integer | Pagination |

**Success Response (200 OK):** Same structure as `GET /elections/{id}/races`.

---

#### `GET /races/{id}`

Returns a single race by ID.

**Success Response (200 OK):**

```json
{
  "id": "race_wv_2024_us_senate",
  "election_id": "wv-2024-11-05-general",
  "office_title": "U.S. Senate",
  "race_type": "candidate",
  "office_level": "federal",
  "geography_scope": "statewide",
  "jurisdiction": "West Virginia",
  "ocd_division_id": "ocd-division/country:us/state:wv",
  "district_id": "dist_wv_statewide",
  "certification_status": "certified",
  "precinct_reporting": 1847,
  "total_precincts": 1847,
  "candidate_count": 3,
  "source": "civic_api",
  "created_at": "2024-09-01T00:00:00Z",
  "updated_at": "2024-11-06T08:30:00Z"
}
```

---

#### `GET /races/{id}/candidates`

Returns all candidates running in a specific race.

**Path Parameters:** `id` — Race ID

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `party` | string | Filter by party abbreviation (e.g., `D`, `R`, `I`) |
| `incumbent` | boolean | Filter to only incumbents (`true`) or challengers (`false`) |

**Success Response (200 OK):**

```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "cand_001",
      "name": "Jane Doe",
      "party": "Democratic",
      "party_abbr": "D",
      "incumbent": false,
      "contact": {
        "email": "jane@janedoe.com",
        "phone": "304-555-0100",
        "website": "https://www.janedoe.com"
      },
      "bio": "Jane Doe is a former state delegate...",
      "platform_statement": "My platform focuses on...",
      "source": "ballotpedia",
      "created_at": "2024-08-15T00:00:00Z",
      "updated_at": "2024-10-01T00:00:00Z"
    }
  ]
}
```

---

#### `GET /races/{id}/results`

Returns vote results for a specific race.

**Path Parameters:** `id` — Race ID

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `result_type` | string | `UNOFFICIAL` or `OFFICIAL` |

**Success Response (200 OK):**

```json
{
  "race_id": "race_wv_2024_us_senate",
  "office_title": "U.S. Senate",
  "result_type": "OFFICIAL",
  "precinct_reporting": 1847,
  "total_precincts": 1847,
  "precinct_reporting_pct": 100.0,
  "last_updated": "2024-11-20T12:00:00Z",
  "results": [
    {
      "id": "res_001",
      "candidate_id": "cand_001",
      "candidate_name": "Jane Doe",
      "option_label": null,
      "party": "D",
      "vote_count": 324512,
      "vote_percentage": 52.3,
      "winner": true,
      "source": "wv_clarity"
    },
    {
      "id": "res_002",
      "candidate_id": "cand_002",
      "candidate_name": "Bob Jones",
      "option_label": null,
      "party": "R",
      "vote_count": 295788,
      "vote_percentage": 47.7,
      "winner": false,
      "source": "wv_clarity"
    }
  ]
}
```

---

### Candidates

---

#### `GET /candidates`

Returns a paginated list of candidates across all races and elections.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `state` | string | 2-letter state abbreviation |
| `election_id` | string | Filter by election |
| `race_id` | string | Filter by race |
| `party` | string | Party abbreviation |
| `incumbent` | boolean | `true` / `false` |
| `name` | string | Partial name match |
| `office_level` | string | `federal`, `state`, `local` |
| `page` / `page_size` | integer | Pagination |

**Success Response (200 OK):** Same structure as `GET /races/{id}/candidates` results.

---

#### `GET /candidates/{id}`

Returns a single candidate's full profile.

**Success Response (200 OK):**

```json
{
  "id": "cand_001",
  "name": "Jane Doe",
  "party": "Democratic",
  "party_abbr": "D",
  "race_id": "race_wv_2024_us_senate",
  "election_id": "wv-2024-11-05-general",
  "office_title": "U.S. Senate",
  "state": "WV",
  "incumbent": false,
  "contact": {
    "email": "jane@janedoe.com",
    "phone": "304-555-0100",
    "website": "https://www.janedoe.com"
  },
  "bio": "Jane Doe is a former state delegate representing Kanawha County...",
  "platform_statement": "My platform focuses on healthcare, education, and economic development...",
  "source": "ballotpedia",
  "source_url": "https://ballotpedia.org/Jane_Doe",
  "created_at": "2024-08-15T00:00:00Z",
  "updated_at": "2024-10-01T00:00:00Z"
}
```

---

### Ballot Measures

---

#### `GET /ballot-measures`

Returns a paginated list of ballot measures.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `state` | string | 2-letter state abbreviation |
| `election_id` | string | Filter by election |
| `measure_type` | string | `resolution`, `referendum`, `initiative`, `constitutional_amendment`, `bond`, `recall` |
| `measure_subtype` | string | `direct` or `indirect` |
| `page` / `page_size` | integer | Pagination |

**Success Response (200 OK):**

```json
{
  "count": 4,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "bm_001",
      "election_id": "wv-2024-11-05-general",
      "race_id": "race_wv_2024_amendment1",
      "title": "Amendment 1 — State Authorization of Religious Expression",
      "measure_type": "constitutional_amendment",
      "measure_subtype": "indirect",
      "summary": "Amends the state constitution to...",
      "state": "WV",
      "source": "ballotpedia",
      "created_at": "2024-09-01T00:00:00Z",
      "updated_at": "2024-10-15T00:00:00Z"
    }
  ]
}
```

---

#### `GET /ballot-measures/{id}`

Returns a single ballot measure's full detail, including full text and voting options.

**Success Response (200 OK):**

```json
{
  "id": "bm_001",
  "election_id": "wv-2024-11-05-general",
  "race_id": "race_wv_2024_amendment1",
  "title": "Amendment 1 — State Authorization of Religious Expression",
  "measure_type": "constitutional_amendment",
  "measure_subtype": "indirect",
  "summary": "Amends the state constitution to clarify state authorization of religious expression...",
  "full_text": "Be it resolved by the Legislature of West Virginia...",
  "state": "WV",
  "ocd_division_id": "ocd-division/country:us/state:wv",
  "options": [
    { "label": "For the Amendment", "option_type": "yes" },
    { "label": "Against the Amendment", "option_type": "no" }
  ],
  "source": "ballotpedia",
  "source_url": "https://ballotpedia.org/West_Virginia_Amendment_1_(2024)",
  "created_at": "2024-09-01T00:00:00Z",
  "updated_at": "2024-10-15T00:00:00Z"
}
```

---

### Officials

---

#### `GET /officials`

Returns current elected officials.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `state` | string | 2-letter state abbreviation |
| `office_level` | string | `federal`, `state`, `local` |
| `office_title` | string | Partial match (e.g., `Governor`, `Senator`) |
| `party` | string | Party abbreviation |
| `district_id` | string | OCD-ID of district |
| `incumbent` | boolean | Always `true` for current officials; included for consistency |
| `page` / `page_size` | integer | Pagination |

**Success Response (200 OK):**

```json
{
  "count": 5,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "off_001",
      "name": "John Smith",
      "office_title": "U.S. Senator",
      "party": "Republican",
      "party_abbr": "R",
      "state": "WV",
      "district_id": "dist_wv_statewide",
      "ocd_division_id": "ocd-division/country:us/state:wv",
      "incumbent": true,
      "term_start": "2021-01-03",
      "term_end": "2027-01-03",
      "contact": {
        "phone": "202-555-0100",
        "website": "https://smith.senate.gov"
      },
      "source": "google_civic",
      "created_at": "2021-01-04T00:00:00Z",
      "updated_at": "2024-11-15T00:00:00Z"
    }
  ]
}
```

---

#### `GET /officials/{id}`

Returns a single official's full record.

**Success Response (200 OK):** Same shape as a single item in `GET /officials`, with additional fields:

```json
{
  "id": "off_001",
  "name": "John Smith",
  "office_title": "U.S. Senator",
  "party": "Republican",
  "party_abbr": "R",
  "state": "WV",
  "district_id": "dist_wv_statewide",
  "ocd_division_id": "ocd-division/country:us/state:wv",
  "incumbent": true,
  "term_start": "2021-01-03",
  "term_end": "2027-01-03",
  "contact": {
    "email": "senator@smith.senate.gov",
    "phone": "202-555-0100",
    "website": "https://smith.senate.gov",
    "address": "123 Russell Senate Office Building, Washington, DC 20510"
  },
  "source": "google_civic",
  "source_url": "https://www.googleapis.com/civicinfo/v2/representatives",
  "created_at": "2021-01-04T00:00:00Z",
  "updated_at": "2024-11-15T00:00:00Z"
}
```

---

### Districts

---

#### `GET /districts`

Returns a paginated list of districts.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `state` | string | 2-letter state abbreviation |
| `level` | string | `federal`, `state`, `local` |
| `office_type` | string | `house`, `senate`, `governor`, `state_upper`, `state_lower`, `county`, `municipal`, `school_board`, `special` |
| `fips_code` | string | FIPS code (state or county) |
| `page` / `page_size` | integer | Pagination |

**Success Response (200 OK):**

```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "dist_wv_cd2",
      "name": "West Virginia 2nd Congressional District",
      "ocd_division_id": "ocd-division/country:us/state:wv/cd:2",
      "fips_code": "54",
      "level": "federal",
      "office_type": "house",
      "state": "WV",
      "parent_district_id": "dist_wv_statewide",
      "source": "census",
      "created_at": "2020-01-01T00:00:00Z",
      "updated_at": "2022-06-01T00:00:00Z"
    }
  ]
}
```

---

#### `GET /districts/{id}`

Returns a single district's metadata (without boundary geometry).

**Success Response (200 OK):** Single object matching the shape above.

---

#### `GET /districts/{id}/boundary`

Returns the GeoJSON boundary polygon for a district. This is a separate endpoint because GeoJSON payloads can be large — lazy-load only when needed.

**Success Response (200 OK):**

```json
{
  "district_id": "dist_wv_cd2",
  "ocd_division_id": "ocd-division/country:us/state:wv/cd:2",
  "geojson": {
    "type": "Feature",
    "properties": {
      "district_id": "dist_wv_cd2",
      "name": "West Virginia 2nd Congressional District"
    },
    "geometry": {
      "type": "MultiPolygon",
      "coordinates": [ [ [ [-81.7, 38.2], [-80.9, 38.2], [-80.9, 39.7], [-81.7, 39.7], [-81.7, 38.2] ] ] ]
    }
  },
  "source": "census_tiger",
  "vintage": "2022"
}
```

**Error Responses:**

| Status | Code | Description |
|---|---|---|
| `404` | `NOT_FOUND` | District ID does not exist |
| `404` | `NO_BOUNDARY` | District exists but no boundary data has been ingested yet |

---

## Data Models

### Election

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique election ID |
| `name` | string | Human-readable name |
| `election_date` | date | ISO 8601 date |
| `election_type` | string | `primary`, `general`, `special`, `midterm`, `party` |
| `primary_type` | string\|null | `open`, `closed`, `nonpartisan`, `jungle` — only set when `election_type=primary` |
| `state` | string | 2-letter abbreviation |
| `state_fips` | string | FIPS code (e.g., `"54"` for WV) |
| `ocd_division_id` | string | OCD division identifier |
| `status` | string | `upcoming`, `active`, `certified` |
| `results_url` | string\|null | External results URL (e.g., Clarity Elections link); admin-set |
| `race_count` | integer | Number of races in this election |
| `source` | string | Ingest source key |
| `created_at` | datetime | ISO 8601 |
| `updated_at` | datetime | ISO 8601 |

### Race

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique race ID |
| `election_id` | string | Parent election ID |
| `office_title` | string | Office name (e.g., `"U.S. Senate"`) or measure title |
| `race_type` | string | `candidate` or `measure` |
| `office_level` | string | `federal`, `state`, `local` |
| `geography_scope` | string | `statewide`, `district`, `county`, `municipal` |
| `jurisdiction` | string | Plain-text jurisdiction name |
| `ocd_division_id` | string | OCD division |
| `district_id` | string\|null | Linked district record |
| `certification_status` | string | `upcoming`, `results_pending`, `certified` |
| `precinct_reporting` | integer | Precincts reporting |
| `total_precincts` | integer | Total precincts |
| `candidate_count` | integer | Number of candidates |
| `source` | string | Ingest source key |

### Candidate

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique candidate ID |
| `name` | string | Full name |
| `party` | string | Full party name |
| `party_abbr` | string | Abbreviation (e.g., `D`, `R`, `I`) |
| `race_id` | string | Race this candidate is in |
| `election_id` | string | Parent election |
| `office_title` | string | Office sought |
| `state` | string | 2-letter state |
| `incumbent` | boolean | Whether this candidate is the current officeholder |
| `contact.email` | string\|null | Campaign email |
| `contact.phone` | string\|null | Campaign phone |
| `contact.website` | string\|null | Campaign website URL |
| `bio` | string\|null | Biographical description |
| `platform_statement` | string\|null | Candidate's platform text |
| `source` | string | Ingest source key |
| `source_url` | string\|null | Source record URL |

### BallotMeasure

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique measure ID |
| `election_id` | string | Parent election |
| `race_id` | string | Parent race |
| `title` | string | Measure title |
| `measure_type` | string | `resolution`, `referendum`, `initiative`, `constitutional_amendment`, `bond`, `recall` |
| `measure_subtype` | string\|null | `direct`, `indirect` |
| `summary` | string\|null | Short description (truncated to 2000 chars for display) |
| `full_text` | string\|null | Complete measure text |
| `state` | string | 2-letter state |
| `ocd_division_id` | string | OCD division |
| `options` | array | Voting options (e.g., `[{label: "Yes", option_type: "yes"}, ...]`) |
| `source` | string | Ingest source key |
| `source_url` | string\|null | Source record URL |

### Official

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique official ID |
| `name` | string | Full name |
| `office_title` | string | Current office held |
| `party` | string | Party name |
| `party_abbr` | string | Party abbreviation |
| `state` | string | 2-letter state |
| `district_id` | string | District represented |
| `ocd_division_id` | string | OCD division |
| `incumbent` | boolean | Always `true` for active officials |
| `term_start` | date | ISO 8601 term start date |
| `term_end` | date\|null | ISO 8601 term end date (null if indefinite) |
| `contact.email` | string\|null | Official contact email |
| `contact.phone` | string\|null | Official phone |
| `contact.website` | string\|null | Official website |
| `contact.address` | string\|null | Office address |
| `source` | string | Ingest source key |

### District

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique district ID |
| `name` | string | Human-readable name |
| `ocd_division_id` | string | OCD division identifier |
| `fips_code` | string | FIPS state or county code |
| `level` | string | `federal`, `state`, `local` |
| `office_type` | string | `house`, `senate`, `governor`, `state_upper`, `state_lower`, `county`, `municipal`, `school_board`, `special` |
| `state` | string | 2-letter state |
| `parent_district_id` | string\|null | Parent district (e.g., state for a CD) |
| `source` | string | Ingest source key |

### Result

| Field | Type | Description |
|---|---|---|
| `id` | string | Unique result ID |
| `race_id` | string | Parent race |
| `candidate_id` | string\|null | Candidate (null for measure options) |
| `candidate_name` | string | Candidate or option name |
| `option_label` | string\|null | For measure options: `"For the Amendment"`, `"Against"`, etc. |
| `party` | string\|null | Party abbreviation |
| `vote_count` | integer | Total votes |
| `vote_percentage` | float | Percentage of total votes |
| `winner` | boolean\|null | `true` if winner; `null` if not yet determined |
| `result_type` | string | `UNOFFICIAL` or `OFFICIAL` |
| `source` | string | Ingest source key |

---

## Error Handling

All errors follow a consistent JSON envelope:

```json
{
  "error": "ERROR_CODE",
  "message": "Human-readable description of the problem.",
  "detail": { }
}
```

### Error Code Reference

| HTTP Status | Error Code | Meaning |
|---|---|---|
| `400` | `MISSING_LOCATION` | Lookup called without `address` or `zip` |
| `400` | `INVALID_ADDRESS` | Address provided could not be geocoded |
| `400` | `INVALID_PARAMETER` | A query parameter has an invalid value |
| `404` | `NOT_FOUND` | The requested resource does not exist |
| `404` | `NO_CONTESTS` | Valid address; no active contests in this jurisdiction |
| `404` | `NO_BOUNDARY` | District exists but no boundary geometry is available |
| `429` | `RATE_LIMIT_EXCEEDED` | Too many requests; see `Retry-After` header |
| `503` | `UPSTREAM_UNAVAILABLE` | A required upstream source (e.g., Google Civic API) is unreachable |

### Common Scenarios

**Address not found:**
```json
{
  "error": "INVALID_ADDRESS",
  "message": "The address '999 Fake St' could not be geocoded.",
  "detail": { "address": "999 Fake St" }
}
```

**No contests (valid state, no active election):**
```json
{
  "error": "NO_CONTESTS",
  "message": "No active contests were found for this address. This is not an error — there may be no upcoming election in this jurisdiction.",
  "detail": { "address": "123 Main St, Charleston, WV 25301" }
}
```

---

## Rate Limiting

| Tier | Limit | Header |
|---|---|---|
| Anonymous | 60 req/min | `X-RateLimit-Limit: 60` |
| API Key | 600 req/min | `X-RateLimit-Limit: 600` |

Rate limit headers are included on every response:

```
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 42
X-RateLimit-Reset: 1700000060
```

On `429 Too Many Requests`:
```
Retry-After: 30
```

---

## Changelog

| Version | Date | Notes |
|---|---|---|
| v1 | 2026-05-17 | Initial endpoint design; pre-implementation |

---

## See Also

- [`ADR-001-API-Endpoint-Structure.md`](../ADRs/ADR-001-API-Endpoint-Structure.md) — Architecture decision record for this design
- [`concept.md`](../concept.md) — Project concept and data source catalog
- [`State Research/COVERAGE-ANALYSIS-RESULTS.md`](../State%20Research/COVERAGE-ANALYSIS-RESULTS.md) — Per-state data coverage analysis

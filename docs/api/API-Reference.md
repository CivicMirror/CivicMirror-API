# CivicMirror API — Reference

**Base URL (Production):** `https://civicmirror-api-866677508588.us-central1.run.app`
**Custom Domain:** `https://api.civicmirror.welshrd.com` *(canonical — use this in frontend builds)*
**API Version:** v1
**All endpoints prefixed with:** `/api/v1/` (an unversioned `/api/` alias also exists — see note below)

---

## Authentication

There are three independent auth mechanisms layered on this API:

### 1. API key (required on almost everything under `/api/`)

```
X-Api-Key: <CIVICMIRROR_API_KEY>
```

Requests without a valid key return `403 Forbidden`. The key is stored in GCP Secret Manager as `CIVICMIRROR_API_KEY` and mounted into the Cloud Run service. Two endpoints are explicitly exempt: `GET /health/` and `GET /api/v1/coverage/sync-status/` (both `AllowAny`).

### 2. Firebase ID token (mock voting, community submissions, `/users/me/`, `/users/votes/`)

```
X-Api-Key: <key>
Authorization: Bearer <firebase_id_token>
```

Decoded via `firebase_admin`; the resulting `uid` identifies the user. If `FIREBASE_AUTH_ENABLED=False` or Firebase isn't initialized, this backend passes through silently (falls back to DRF Token auth, below).

### 3. DRF Token auth (legacy `accounts` app — Django `User` model, not Firebase)

```
Authorization: Token <token>
```

Obtained from `POST /api/auth/login/` or `POST /api/auth/register/`. This system is **separate** from the Firebase-backed `UserProfile`/`MockVote` system in point 2 — same header slot (`Authorization`), different scheme prefix (`Token` vs `Bearer`) and a different user identity model. The mock-voting/community endpoints accept either a Firebase Bearer token or a DRF Token — whichever authenticates first wins.

**Note:** the `accounts` app (`/api/auth/...`, `/api/users/me/profile/`) is mounted **only** at `/api/`, not `/api/v1/`. Everything else (`api.urls`, which includes `community.urls`) is mounted at both `/api/` and `/api/v1/` identically — use `/api/v1/` for new integrations.

---

## Pagination

All list endpoints (DRF viewsets) are paginated using page-number pagination.

| Parameter | Default | Description |
|---|---|---|
| `page` | 1 | Page number |
| `page_size` | 25 | Items per page (DRF default) |

**Response envelope:**
```json
{
  "count": 150,
  "next": "https://.../api/v1/elections/?page=2",
  "previous": null,
  "results": [ ... ]
}
```

Hand-written `APIView` endpoints (`/lookup/`, `/races/{id}/results/`, `/races/{id}/candidates/`, tally, vote, community, user profile/votes) return plain arrays or objects — **not** the paginated envelope. See each endpoint below.

---

## Common Query Parameters

All DRF-router list endpoints (`elections/`, `races/`, `candidates/`, `ballot-measures/`, `districts/`) support:

| Parameter | Description | Example |
|---|---|---|
| `search` | Full-text search across key text fields | `?search=senate` |
| `ordering` | Sort field (prefix `-` for descending) | `?ordering=-election_date` |

---

## Endpoints

### `GET /api/v1/elections/`

List all elections.

**Filters:**

| Param | Type | Description |
|---|---|---|
| `state` | string (2-char, case-insensitive) | Filter by state abbreviation: `?state=WV` |
| `status` | string | `upcoming` · `active` · `results_pending` · `results_certified` · `archived` |
| `jurisdiction_level` | string | `national` · `state` · `local` |
| `election_date__gte` | date (YYYY-MM-DD) | Elections on or after date |
| `election_date__lte` | date (YYYY-MM-DD) | Elections on or before date |

**Ordering fields:** `election_date`, `name`, `state`
**Search fields:** `name`, `state`
**Default ordering:** `election_date`

**Response shape:**
```json
{
  "count": 12,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "source_id": "2000",
      "name": "2026 West Virginia Primary",
      "election_date": "2026-05-12",
      "election_type": "primary",
      "jurisdiction_level": "state",
      "state": "WV",
      "status": "upcoming",
      "last_synced_at": "2026-05-19T10:00:00Z",
      "election_cycle": {
        "id": 1,
        "cycle_year": 2026,
        "description": "2026 Midterm Cycle",
        "cycle_start": "2026-01-01",
        "cycle_end": "2026-12-31"
      },
      "race_count": 14,
      "sources": ["civic_api", "openstates"],
      "field_provenance": {}
    }
  ]
}
```

`election_type` choices: `general` · `primary` · `primary_runoff` · `special` · `general_runoff` · `municipal` · `party` · `other` (default `general`).

`sources` (`contributing_sources`) lists every integration that has written to this record; `field_provenance` maps individual field names to the source that last set them — both exist to support cross-source merge/reconciliation and are informational only.

---

### `GET /api/v1/elections/{id}/`

Retrieve a single election. **Response:** Same shape as list item above.

---

### `GET /api/v1/elections/{id}/races/`

All races for a specific election, restricted to `race_status` in `active`/`archived` (the "public" queryset). Paginated. Returns full `RaceDetail` objects including nested candidates/measure_options — see `GET /api/v1/races/{id}/` detail shape.

---

### `GET /api/v1/races/`

List races (summary shape — no nested candidates). Numeric-only `{id}` lookups (`lookup_value_regex = r'\d+'`) so the static `races/community/` and `races/ext/...` prefixes below route correctly instead of being swallowed as a pk.

**Filters:**

| Param | Type | Description |
|---|---|---|
| `election` | integer | Filter by election ID |
| `race_type` | string | `candidate` · `measure` |
| `race_status` | string | `draft` · `pending_review` · `active` · `cancelled` · `archived` |
| `certification_status` | string | `upcoming` · `results_pending` · `results_certified` · `partial_results` |
| `state` | string (2-char) | Filter by election's state |
| `geography_scope` | string (case-insensitive) | e.g. `statewide`, `congressional`, `county` |
| `jurisdiction_level` | string | Filter by the related election's `jurisdiction_level`: `national` · `state` · `local` |
| `source` | string | `civic_api` · `openelections` · `medsl` · `community` · `results_adapter` · plus one value per state integration (e.g. `oh_sos`, `va_elect`, `ny_boe`, ...) |

**Ordering fields:** `office_title`, `election__election_date`
**Search fields:** `office_title`, `jurisdiction`

**List response shape (RaceListSerializer):**
```json
{
  "results": [
    {
      "id": 5,
      "election": 1,
      "race_type": "candidate",
      "office_title": "U.S. Senate",
      "jurisdiction": "West Virginia",
      "geography_scope": "statewide",
      "certification_status": "upcoming",
      "race_status": "active",
      "vote_method": "single_choice",
      "ocd_division_id": "ocd-division/country:us/state:wv",
      "source": "civic_api",
      "last_synced_at": "2026-05-19T10:00:00Z"
    }
  ]
}
```

---

### `GET /api/v1/races/{id}/`

Retrieve a single race with full detail including nested candidates and measure options.

**Detail response shape (RaceDetailSerializer):**
```json
{
  "id": 5,
  "election": 1,
  "race_type": "candidate",
  "office_title": "U.S. Senate",
  "jurisdiction": "West Virginia",
  "geography_scope": "statewide",
  "certification_status": "upcoming",
  "race_status": "active",
  "vote_method": "single_choice",
  "max_selections": 1,
  "ballot_type": "",
  "ocd_division_id": "ocd-division/country:us/state:wv",
  "normalized_office_title": "us_senate",
  "yes_vote_details": "",
  "no_vote_details": "",
  "match_confidence": "verified",
  "source": "civic_api",
  "last_synced_at": "2026-05-19T10:00:00Z",
  "candidates": [
    {
      "id": 12,
      "name": "Jane Smith",
      "party": "Democratic",
      "incumbent": true,
      "candidate_status": "running",
      "description": "",
      "image_url": "",
      "website_url": "https://janesmith.com",
      "fec_candidate_id": "S0WV00123",
      "bioguide_id": "",
      "openstates_person_id": "",
      "contact_phone": "",
      "contact_office": "",
      "race": 5,
      "field_provenance": {}
    }
  ],
  "measure_options": [],
  "sources": ["civic_api"],
  "field_provenance": {}
}
```

`vote_method` choices: `single_choice` · `multi_seat` · `ranked_choice` · `yes_no`.
`match_confidence` choices: `verified` · `high` · `medium` · `low` · `flagged`.

> **Note:** `incumbent` is reliably populated for state legislators sourced from OpenStates (all 50 states). `party`, `website_url`, and `contact_phone` are also now populated from OpenStates as of v1.1.5.

---

### `GET /api/v1/races/{id}/candidates/`

Candidates for a specific race. Returns a plain array of `CandidateSerializer` objects (same shape as nested above) — **no pagination envelope**.

---

### `GET /api/v1/races/{id}/results/`

Official results for a specific race. Returns a plain array — **not** paginated (bounded by the race's candidate/option count; the frontend `.map()`s this response directly, so it must stay an array, not `{count,next,previous,results}`).

**Response shape:**
```json
[
  {
    "id": 1,
    "race": 5,
    "candidate": 12,
    "measure_option": null,
    "vote_count": 142500,
    "vote_pct": "52.30",
    "result_type": "unofficial",
    "is_winner": true,
    "round_number": null,
    "jurisdiction_fragment": "",
    "is_write_in_aggregate": false,
    "certified_at": null,
    "source_url": "https://results.enr.clarityelections.com/WV/..."
  }
]
```

> **Note:** `result_type` will be `"unofficial"` until an admin explicitly marks results as certified.
> For ballot measures: `candidate` is `null`, `measure_option` is an integer ID.

---

### `GET /api/v1/ballot-measures/`

List ballot measure races only (`race_type=measure`). Same filter/shape as `/races/`.

---

### `GET /api/v1/ballot-measures/{id}/`

Single ballot measure detail. Same shape as `/races/{id}/` with `measure_options` populated.

---

### `GET /api/v1/candidates/`

List candidates across all races.

**Filters:**

| Param | Type | Description |
|---|---|---|
| `race` | integer | Filter by race ID |
| `party` | string (case-insensitive contains) | e.g. `?party=democrat` |
| `incumbent` | boolean | `?incumbent=true` |
| `candidate_status` | string | `running` · `withdrawn` · `disqualified` · `write_in` |

**Ordering fields:** `name`, `party`
**Search fields:** `name`, `party`

---

### `GET /api/v1/districts/`

List district records.

**Filters:**

| Param | Type | Description |
|---|---|---|
| `state` | string (2-char, case-insensitive) | `?state=WV` |
| `district_type` | string | e.g. `congressional`, `state_senate`, `county` |

**Ordering fields:** `name`, `state`, `district_type`
**Search fields:** `name`, `ocd_division_id`

**Response shape:**
```json
{
  "results": [
    {
      "id": 3,
      "state": "WV",
      "district_type": "congressional",
      "district_number": "2",
      "ocd_division_id": "ocd-division/country:us/state:wv/cd:2",
      "name": "West Virginia 2nd Congressional District",
      "fips_code": "54",
      "election_year_valid": 2026,
      "approximate": false,
      "last_updated": "2026-05-19T10:00:00Z"
    }
  ]
}
```

---

### `GET /api/v1/lookup/?zip=<ZIP>`

**The primary front-end entry point.** Given a ZIP code, returns all active elections for that state with full race details (candidates + measure options) — ready to render a ballot.

**Query parameters:**

| Param | Required | Description |
|---|---|---|
| `zip` | ✅ | 5-digit ZIP code |
| `election_id` | ❌ | Limit to a specific election ID |

**Response shape:**
```json
[
  {
    "election": { /* ElectionSerializer */ },
    "races": [ /* RaceDetailSerializer[], only active/archived races */ ]
  }
]
```

**Error responses:**
- `400` — `{"error": "zip parameter is required"}`
- `400` — `{"error": "Invalid or unrecognized ZIP code"}`
- `400` — `{"error": "election_id must be an integer"}`
- `200` with `[]` — Valid ZIP but no active elections for that state
- `200` with `[{"election": ..., "races": []}]` — Election exists but no race data available (state submitted polling-location-only VIP feed — not an error)

---

### `GET /api/v1/coverage/sync-status/`

Public (`AllowAny` — **no** `X-Api-Key` required). Powers the `/coverage` page: most recent completed sync per data source, grouped by state, plus the live set of states with a registered results adapter and a computed coverage tier per state.

**Response shape:**
```json
{
  "as_of": "2026-07-25T12:00:00Z",
  "global": {
    "civic_api": {
      "last_completed_at": "2026-07-25T06:00:00Z",
      "status": "completed",
      "records_created": 12,
      "records_updated": 340,
      "records_skipped": 0
    }
  },
  "by_state": {
    "OH": {
      "oh_sos": { "last_completed_at": "...", "status": "completed", "records_created": 0, "records_updated": 50, "records_skipped": 2 }
    }
  },
  "adapter_states": ["AR", "OH", "SC", "..."],
  "coverage_tiers": { "AL": "full", "KY": "state", "OH": "results", "...": "..." }
}
```

`coverage_tiers` values: `full` (Full Core integration merged), `state` (state-level sync integration built, no live results adapter yet), `results` (results adapter only, derived from `list_supported_states()`).

---

## Health Check

```
GET /health/
```

No auth required. Returns `{"status": "ok"}` with HTTP 200.

---

## Mock Voting

Requires **both** `X-Api-Key` and a user identity — either `Authorization: Bearer <firebase_id_token>` or `Authorization: Token <drf_token>` (see Authentication above). Voting endpoints are mounted under `community.urls`, included by `api.urls`, so they exist at both `/api/` and `/api/v1/`.

### `POST /api/v1/races/{pk}/vote/`

Submit a mock vote for a race (looked up by internal integer PK). The race's `race_status` must be `active`, or this returns `400`.

**Request body:**
```json
{
  "candidate_ids": [12],
  "measure_option_id": null,
  "ranked_selections": null
}
```

Use `candidate_ids` (array) for `single_choice`, `multi_seat`, and `yes_no` races — exactly one ID for `single_choice`/`yes_no`, up to `race.max_selections` for `multi_seat`.
Use `ranked_selections` (ordered array of candidate IDs, no duplicates) for `ranked_choice` races.
Use `measure_option_id` (integer) for `measure` races (nothing else may be set).

**Response `201 Created`:**
```json
{
  "id": 101,
  "race": 5,
  "selection_type": "candidate",
  "candidate_ids": [12],
  "measure_option_id": null,
  "ranked_selections": null,
  "created_at": "2026-05-21T14:00:00Z"
}
```

**Error responses:**
- `401` — `{"detail": "Authentication required."}` — no valid Firebase/Token credential
- `400` — `{"error": "Voting is not open for this race."}` — race is not `active`
- `400` — `{"error": "<reason>"}` — payload doesn't match the race's `vote_method` (see `community/services.py::_validate_vote_payload` for the exact message per case: missing/duplicate/invalid IDs, wrong field for the vote method, too many selections, etc.)
- `409 Conflict` — `{"error": "You have already voted on this race."}` — one vote per `(uid, race)`, enforced by a DB unique constraint

---

### `POST /api/v1/races/ext/{external_id}/vote/`

Submit a mock vote using the race's `canonical_key` (its external/VIP ID) instead of the internal integer PK. Same body, validation, and response shape as `/api/v1/races/{id}/vote/`.

---

### `GET /api/v1/races/{pk}/tally/`

Current mock vote tally for a race. Requires `X-Api-Key` only — no user auth (tally is public).

**Response `200 OK`:**
```json
{
  "race_id": 5,
  "total_votes": 1523,
  "options": [
    { "id": 12, "label": "Jane Smith", "type": "candidate", "count": 845, "percent": 55.5 },
    { "id": 14, "label": "Bob Jones", "type": "candidate", "count": 678, "percent": 44.5 }
  ],
  "breakdowns": {}
}
```

For `ranked_choice` races, only first-choice selections are counted. For measure races, options are keyed by `measure_option_id` with `type: "measure_option"`.

---

### `GET /api/v1/races/ext/{external_id}/tally/`

Tally by canonical/external race ID. Same response shape as above.

---

### `GET /api/v1/users/votes/`

Authenticated user's mock vote history. Requires Firebase or Token auth.

**Response `200 OK`:**
```json
[
  {
    "id": 101,
    "race": 5,
    "race_title": "U.S. Senate — West Virginia",
    "election_name": "2026 West Virginia Primary",
    "selection_summary": "Jane Smith",
    "created_at": "2026-05-21T14:00:00Z"
  }
]
```

---

## Community Race Submission

Community races use the same `Race` data model as VIP-sourced races. `source` values: `civic_api`/other integration values (VIP/Google/state feeds) vs. `community` (user-submitted). Community-submitted races start with `race_status: "pending_review"` and require admin approval (a manual status change, no dedicated endpoint yet) to become `"active"`.

### `POST /api/v1/races/community/`

Submit a new community race. Requires Firebase or Token auth.

`election_id` is **optional**. If omitted, an `Election` is auto-created (or reused, keyed on `election_date` + `location_name`) from `election_date`/`location_name` in the payload — submitters never need to look up or create an election themselves. Pass `election_id` only to attach a race to an election that already exists.

**Request body (candidate race):**
```json
{
  "race_type": "candidate",
  "office_title": "Morgantown City Council District 3",
  "jurisdiction": "city",
  "election_date": "2026-11-03",
  "location_name": "Morgantown, WV",
  "candidates": [
    { "name": "John Doe", "party": "Independent", "candidate_type": "running", "website_url": "" },
    { "name": "Alice Kim", "party": "Independent", "candidate_type": "running", "website_url": "" }
  ],
  "source_url": "https://morgantowncity.gov/elections/2026"
}
```

`office_title`, `race_type`, and at least one `candidates[].name` are required. `geography_scope` is read from `geography_scope` if present, otherwise falls back to `jurisdiction`. `vote_method` defaults to `single_choice` if omitted. Each candidate accepts `name`, `party`, `description`, `image_url`, `website_url`, `candidate_type` (`running` default, or `write_in`).

**Request body (ballot measure):**
```json
{
  "race_type": "measure",
  "question_title": "Should the town build a new park?",
  "ballot_type": "Citizen-Initiated",
  "election_date": "2026-11-03",
  "location_name": "Springfield",
  "yes_vote_details": "A yes vote supports building the park.",
  "no_vote_details": "A no vote opposes building the park.",
  "source_links": ["https://example.com/measure"]
}
```

`question_title` (maps to `office_title`), `yes_vote_details`, and `no_vote_details` are required. Two `MeasureOption` rows (`"Yes"` / `"No"`) are auto-created so the race is immediately votable. `vote_method` defaults to `yes_no` if omitted. `geography_scope` defaults to `"local"` since measures don't collect a jurisdiction type.

Either race type: `election_date` (`YYYY-MM-DD`) and `location_name` are required unless `election_id` is supplied. `canonical_key` is auto-generated as `community:<uuid4 hex>`.

**Response `201 Created`:** Full `RaceDetail` object with `source: "community"` and `race_status: "pending_review"`.

**Error responses:**
- `401` — `{"detail": "Authentication required."}`
- `400` — `{"error": "<field> is required."}` — missing required field (`office_title`/`question_title`, `jurisdiction`, `election_date`, `location_name`, at least one candidate, `yes_vote_details`/`no_vote_details`, depending on race type)
- `400` — `{"error": "Invalid election_id."}`
- `400` — `{"error": "Invalid race_type: <value>"}`
- `400` — `{"error": "Invalid vote_method: <value>"}`

---

### `GET /api/v1/races/?source=community`

Filter races by source using the existing `/api/v1/races/` list endpoint (see `source` filter above).

---

### `PATCH /api/v1/races/community/{id}/`

Update a community race submission. Requires the submitter's Firebase/Token identity — `race.submitted_by_uid` must match the caller's `uid`, or this returns `403`. Only races with `source=community` are matched (`404` otherwise).

Accepted fields: `office_title`, `jurisdiction`, `source_url` (rewrites `source_links`), `candidates` (replaces **all** candidates on the race — full array, not a diff).

**Response `200 OK`:** Full `RaceDetail` object.

**Error responses:**
- `401` — `{"detail": "Authentication required."}`
- `403` — `{"error": "You do not have permission to modify this race."}`
- `404` — no community race with that ID

---

### `DELETE /api/v1/races/community/{id}/`

Retract a community race submission. Only available while `race_status: "pending_review"` — submitter only (same ownership check as PATCH).

**Response:** `204 No Content`
**Error responses:**
- `403` — not the submitter
- `400` — `{"error": "Only pending-review races can be deleted."}`

---

## User Profile (Firebase-identity, `community` app)

Distinct from the `accounts`-app `UserProfile` below — this one is keyed by Firebase/Token `uid`, auto-created on first authenticated call, and tracks mock-voting activity.

### `GET /api/v1/users/me/`

Retrieve the authenticated user's CivicMirror profile. Requires Firebase or Token auth.

**Response `200 OK`:**
```json
{
  "uid": "firebase-uid-abc123",
  "display_name": "",
  "created_at": "2026-05-01T00:00:00Z",
  "vote_count": 12,
  "submission_count": 2
}
```

`vote_count` and `submission_count` are computed properties (not stored), counting `MockVote`s and `community`-sourced `Race`s for this `uid` respectively.

### `PATCH /api/v1/users/me/`

Update `display_name` (truncated to 255 chars). Requires Firebase or Token auth.

---

## Legacy Auth (`accounts` app — Django `User`, DRF Token)

Mounted at `/api/` only (**not** `/api/v1/`). Distinct from the Firebase-based system above; issues a DRF auth token used as `Authorization: Token <token>` on the Firebase-or-Token endpoints described above.

### `POST /api/auth/register/`

```json
{ "username": "optional", "password": "required", "email": "", "age_range": "", "country": "", "us_state": "", "gender": "" }
```
Auto-generates a username if omitted. **Response `201`:** `{"token": "...", "user": {...}, "profile": {...}}`.
**Error:** `400` — missing password, or username already taken.

### `POST /api/auth/login/`

```json
{ "username": "...", "password": "..." }
```
**Response `200`:** `{"token": "...", "user": {...}, "profile": {...}}`.
**Error:** `400` — `{"non_field_errors": ["Unable to log in with provided credentials."]}`.

### `POST /api/auth/logout/`

Requires `Authorization: Token <token>`. Deletes the token. **Response:** `204 No Content`.

### `GET /api/users/me/profile/`

Requires `Authorization: Token <token>`.
**Response `200`:** `{"id": 1, "username": "...", "age_range": "", "country": "", "us_state": "", "gender": "", "saved_zipcode": "", "created_at": "..."}`.

### `PATCH /api/users/me/profile/`

Update any of `age_range`, `country`, `us_state`, `gender`, `saved_zipcode`. Requires `Authorization: Token <token>`.

---

## Internal Task Triggers

> Auth: Cloud Scheduler OIDC token (production) or `X-Internal-Token` header (local dev), via `require_internal_task_token`. All are `POST` only.

Each trigger acquires a per-task idempotency lock (keyed to the current schedule window) before enqueuing a Celery task, and releases it when the task terminally succeeds or fails. If the lock is already held, the endpoint returns `202 {"status": "already_running"}` instead of enqueuing a duplicate run.

| Path | Description |
|------|-------------|
| `/internal/tasks/sync-elections/` | Google Civic API election sync |
| `/internal/tasks/poll-results/` | Poll all pending-results elections for registered state results adapters |
| `/internal/tasks/sync-openstates/` | OpenStates candidate sync (all 50 states) |
| `/internal/tasks/sync-fec/` | FEC candidate sync |
| `/internal/tasks/sync-sc-vrems/` | South Carolina VREMS sync |
| `/internal/tasks/sync-ia-sos/` | Iowa SOS sync |
| `/internal/tasks/sync-co-sos/` | Colorado SOS sync |
| `/internal/tasks/sync-va-elect/` (alias `/internal/tasks/sync-va-elections/`) | Virginia ELECT sync |
| `/internal/tasks/sync-ma-sos/` | Massachusetts SOS election/race sync |
| `/internal/tasks/sync-ocpf-ma/` | Massachusetts OCPF candidate sync |
| `/internal/tasks/sync-ca-sos/` | California SOS sync |
| `/internal/tasks/seed-election-calendar/` | Seed the 2026 election calendar |
| `/internal/tasks/sync-nc-sbe/` | North Carolina SBE election sync |
| `/internal/tasks/sync-nc-candidates/` | North Carolina candidate sync |
| `/internal/tasks/sync-nj-elections/` | New Jersey county URL sync |
| `/internal/tasks/sync-ny-elections/` | New York BOE election sync |
| `/internal/tasks/sync-ny-races/` | New York BOE race sync |
| `/internal/tasks/sync-az-sos/` | Arizona SOS sync |
| `/internal/tasks/sync-ga-sos/` | Georgia SOS sync |
| `/internal/tasks/poll-sc-enr/` | Poll South Carolina ENR for active elections |
| `/internal/tasks/sync-sc-enr-results/` | South Carolina ENR results sync |
| `/internal/tasks/sync-wa-votewa/` | Washington VoteWA sync |
| `/internal/tasks/sync-fl-ew/` | Florida Election Watch sync |
| `/internal/tasks/sync-tx-goelect/` | Texas GoElect sync |
| `/internal/tasks/sync-oh-sos/` | Ohio SOS sync |
| `/internal/tasks/sync-il-sbe/` | Illinois SBE sync |
| `/internal/tasks/sync-mn-sos/` | Minnesota SOS race sync |
| `/internal/tasks/discover-mn-sos/` | Minnesota SOS election discovery |
| `/internal/tasks/sync-mi-sos/` | Michigan SOS sync |
| `/internal/tasks/sync-or-sos/` | Oregon SOS sync |
| `/internal/tasks/sync-ky-sos/` | Kentucky SOS sync |
| `/internal/tasks/sync-pa-sos/` | Pennsylvania SOS sync |
| `/internal/tasks/sync-tn-sos/` | Tennessee SOS sync |
| `/internal/tasks/sync-al-elections/` | Alabama SOS election sync |
| `/internal/tasks/sync-al-fcpa/` | Alabama FCPA candidate sync |
| `/internal/tasks/sync-vt-sos/` | Vermont SOS sync |

Success responses:
- `202 {"task_id": "<celery id>"}` — enqueued
- `202 {"status": "already_running"}` — lock already held for this window
- `503 {"status": "enqueue_failed"}` — Celery broker rejected the task (lock released)

---

## OpenAPI Schema

```
GET /api/schema/          → OpenAPI 3 YAML
GET /api/docs/            → Swagger UI (DEBUG mode only)
```

---

## Reference Choice Values

| Model.field | Values |
|---|---|
| `Election.status` | `upcoming` · `active` · `results_pending` · `results_certified` · `archived` |
| `Election.election_type` | `general` · `primary` · `primary_runoff` · `special` · `general_runoff` · `municipal` · `party` · `other` |
| `Election.jurisdiction_level` | `national` · `state` · `local` |
| `Race.race_type` | `candidate` · `measure` |
| `Race.race_status` | `draft` · `pending_review` · `active` · `cancelled` · `archived` |
| `Race.certification_status` | `upcoming` · `results_pending` · `results_certified` · `partial_results` |
| `Race.vote_method` | `single_choice` · `multi_seat` · `ranked_choice` · `yes_no` |
| `Race.match_confidence` | `verified` · `high` · `medium` · `low` · `flagged` |
| `Race.source` | `civic_api` · `openelections` · `medsl` · `community` · `results_adapter` · `sc_vrems` · `ia_sos` · `co_sos` · `va_elect` · `ma_sos` · `ca_sos` · `wa_votewa` · `fl_ew` · `tx_goelect` · `oh_sos` · `ga_sos` · `il_sbe` · `mn_sos` · `tn_sos` · `or_sos` · `ky_sos` · `al_sos` · `vt_sos` · `nc_sbe` · `ny_boe` |
| `Candidate.candidate_status` | `running` · `withdrawn` · `disqualified` · `write_in` |

---

## Error Codes Summary

| HTTP | Meaning |
|---|---|
| 200 | Success |
| 201 | Created (write endpoints) |
| 202 | Accepted (internal task triggers — enqueued or already running) |
| 204 | No content (logout, delete) |
| 400 | Bad request (missing/invalid params) |
| 401 | Missing or invalid Firebase/Token `Authorization` header (write endpoints) |
| 403 | Missing/invalid `X-Api-Key` header, or not the resource owner |
| 404 | Resource not found |
| 409 | Conflict (e.g. duplicate vote) |
| 500 | Server error |
| 503 | Internal task enqueue failed (Celery broker unavailable) |

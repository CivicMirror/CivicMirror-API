# ADR-008: State Coverage Display — Dedicated `/coverage` Page

## Status
Accepted — 2026-06-04

## Context

CivicMirror now actively tracks 29+ states across three meaningful tiers of integration depth:

- **Full integration** — dedicated SOS adapter (elections + races + results): WV, CO, SC, MA, VA, AZ
- **Results adapter** — live results on election night when `results_url` is set: AR, CT + 20 Clarity Tier A states (AK, DE, HI, ID, IN, KS, LA, ME, MS, MT, ND, NE, NH, NV, OK, RI, SD, VT, WI, WY) + IA
- **Elections only** — races and candidates via Civic API, no dedicated adapter: all other states

Users have no way to know which states have richer data. As coverage expands, this gap becomes a transparency and trust concern. We need a discoverable, maintainable place in the frontend to surface this information.

### Requirements

- Show all 50 states with their current coverage tier
- Clearly communicate what each tier means (e.g., "results available on election night" vs. "elections only")
- Linkable and shareable (so it can be referenced in documentation or from other pages)
- Easy to update when new adapters ship
- Does not clutter the primary browse UX on the HomePage

### Constraints

- Frontend is a React + Vite SPA (no SSR); any "dynamic" data requires an API call
- The coverage tier for a state only changes when a new adapter is deployed — it is not runtime-variable
- The existing `src/utils/usStates.ts` static constant pattern is already established in this codebase

## Decision

Add a dedicated **`/coverage` route** (new `CoveragePage` component) to the frontend, with a **Header nav link** labeled "Coverage" placed between "Browse races" and the auth buttons.

Coverage data is driven by a **static constant in `src/utils/coverage.ts`** — not a live API call. This is updated alongside each adapter deployment.

## Justification

- **Discoverability:** A first-class nav link is the clearest signal to users that this information exists. A footer link or modal is too buried for a feature users actively need when deciding whether to trust the data.
- **Linkability:** A dedicated route (`/coverage`) can be linked from the README, API docs, and "no races found" empty states ("your state may have limited coverage — [see coverage](/coverage)").
- **Static data is correct here:** Coverage tier is a deployment artifact, not a live DB query. Fetching it from the API would add latency and API surface area for data that doesn't change at runtime. The `usStates.ts` file already establishes the static const pattern.
- **Room to grow:** A dedicated page can evolve to include last-sync timestamps (from the API), links to state-filtered race views, and per-state adapter notes without ever touching the HomePage.
- **Separation of concerns:** Keeps the HomePage focused on browsing races. Coverage transparency is a distinct UX concern.

## Consequences

### Positive

- Users understand why some states have richer data than others
- Reduces "why are there no results for my state?" support friction
- Empty-state messages on HomePage can link directly to `/coverage`
- Coverage page can link into the state-filtered race view (`/?state=WV`) for each full-coverage state
- Easy to update: change one constant in `coverage.ts` when a new adapter ships

### Negative

- One additional nav item in the Header (minor visual cost)
- Static const must be kept in sync with adapter deployments (low risk — adapters ship infrequently, and the discrepancy is purely cosmetic)
- Does not show live adapter health (e.g., whether a Clarity `results_url` is actually set for a current election) — that level of detail belongs to a future admin/status dashboard

## Alternatives Considered

### Section on HomePage (below race list)
Rejected: clutters the primary user journey; difficult to find when the race list is long; no stable URL to reference from docs or empty states.

### Footer expansion ("Coverage: 29 states" link)
Rejected: footer has low attention; not enough room for useful detail; not linkable in a natural way.

### Info modal / drawer triggered from Header
Rejected: dialogs are not linkable, not shareable, harder to maintain as the list grows to 50 states.

### API-driven coverage endpoint (`/api/v1/coverage/`)
Deferred: coverage tier is a deployment artifact, not live data. Worth revisiting if we want to surface real-time adapter health (last successful sync, `results_url` status) — but that is a different feature.

## Implementation Notes

- **New file:** `frontend/src/utils/coverage.ts` — exports `COVERAGE_TIERS` constant (map of state code → tier) and `COVERAGE_TIER_LABELS` for display
- **New component:** `frontend/src/pages/CoveragePage.tsx`
- **Route:** `<Route path="/coverage" element={<CoveragePage />} />` in `App.tsx`
- **Header:** Add `<Button component={RouterLink} to="/coverage">Coverage</Button>` between "Browse races" and auth section
- **Empty-state link (future):** The "no races found" Paper on HomePage can link to `/coverage` for context

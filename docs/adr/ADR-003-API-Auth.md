# ADR-003: API Authentication — X-Api-Key Header

## Status
Accepted

## Context

CivicMirror API is an internal API with a single consumer: the CivicMirror web app. There are no public API users, no self-service registration, and no per-user access control requirements. The API only needs to:

1. Reject requests from unauthorized sources (accidental exposure, misconfigured clients)
2. Be simple to configure for the single-consumer use case
3. Work correctly behind Google Cloud Run with no session state

### Options considered

| Option | Fit | Complexity |
|---|---|---|
| X-Api-Key header (chosen) | ✅ Perfect for M2M, stateless | Low |
| JWT / Knox user tokens | ❌ Requires user accounts (overkill) | High |
| OIDC service-to-service | ✅ Keyless, auditable | Medium — requires GCP setup |
| IP allowlist | ❌ Fragile on Cloud Run (dynamic IPs) | Medium |
| No auth (internal only) | ❌ No protection if URL leaks | None |

## Decision

Use a single **`X-Api-Key` header** checked against the `CIVICMIRROR_API_KEY` environment variable.

- All `/api/v1/` endpoints require the header.
- Timing-safe comparison (`constant_time_compare`) prevents timing attacks.
- `CIVICMIRROR_API_KEY` empty → all requests rejected (fail-safe in prod).
- `GET /health/` is exempt (used by Cloud Run health checks).
- Schema/docs endpoints (`/api/schema/`, `/api/docs/`) are exempt (contain no sensitive data).

## Implementation

`backend/api/permissions.py` — `HasAPIKey(BasePermission)` applied as `permission_classes = [HasAPIKey]` on every viewset and the lookup view.

## Production setup

1. Generate a random 32-byte key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Store in GCP Secret Manager as `civicmirror-api-key`
3. Mount in Cloud Run as env var `CIVICMIRROR_API_KEY`
4. Set the same value as `CIVICMIRROR_API_KEY` in the CivicMirror frontend's Cloud Run environment
5. Rotate by updating both secrets simultaneously

## Local development

Add to `backend/.env`:
```
CIVICMIRROR_API_KEY=dev-local-key
```

Include `X-Api-Key: dev-local-key` in requests (or configure the frontend `.env.local`).

## Consequences

### Positive
- Zero infrastructure overhead — just an env var and a single header
- Easily testable: override `CIVICMIRROR_API_KEY` in test settings
- Stateless — works seamlessly with Cloud Run scale-to-zero

### Negative
- Key rotation requires coordinated update of both the API and the frontend
- Single key — any key exposure compromises all endpoints (mitigated by Secret Manager audit logging)
- Future: if third-party consumers are added, migrate to per-client keys or OIDC

## Related Decisions

- ADR-001: API Endpoint Structure
- ADR-002: Scheduler Architecture

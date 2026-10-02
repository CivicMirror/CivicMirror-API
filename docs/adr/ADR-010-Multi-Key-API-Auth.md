# ADR-010: Per-Client Service API Keys with Access Levels

## Status
Accepted. Supersedes [ADR-003](ADR-003-API-Auth.md). Tracking issue: #201.

## Context

ADR-003 assumed a single consumer (the CivicMirror web app) and one shared `CIVICMIRROR_API_KEY`. That no longer holds. The project is opening the API to a small number of individually approved outside testers, developers, and organizations, starting with the CivicData project. With a single shared key:

- one client's access can't be revoked without rotating every client;
- usage can't be traced back to a specific client;
- there are no scopes, so every key holder has full access;
- the key is built into the FrontEnd's browser bundle, so it's effectively public.

The API also serves two different audiences that shouldn't share an access model:

| | Service API keys | Public user accounts |
|---|---|---|
| Who | People and organizations that pull election data or help maintain it | The general public using the FrontEnd |
| Access granted by | Individual approval by the project owner | Self-registration (Firebase or `accounts` DRF Token) |
| Can do | `read`: pull data. `read_write`: help maintain data. | Mock voting, community race submissions, profile |

## Decision

1. **`ApiKey` model** (`api.models.ApiKey`) with one record per approved client: `name`, `owner`, unique public `prefix`, unique `hashed_key` (SHA-256), `access_level` (`read` | `read_write`), `is_active`, optional `expires_at`, optional `throttle_rate`, `notes`, `created_at`, `last_used_at`.
2. **Keys are generated only on the server**, formatted `cm_<8 hex>_<token_urlsafe(32)>`. Only the hash is stored; the plaintext is shown once. Unsalted SHA-256 is acceptable because the secret is 256 bits of randomness, not a password. The embedded prefix lets logs say *which* key was presented, even a revoked one, without logging the secret.
3. **`HasAPIKey` stays the single gate** on every view that already uses it. It now also enforces the access level, so the check can't be forgotten on an individual view:
   - data views (the default): `read` keys may use only `SAFE_METHODS`;
   - views with `api_key_scope = 'public'` (all `community` views) accept any valid key, because they authenticate the end user themselves and return `401` without one.
4. **Legacy key:** `CIVICMIRROR_API_KEY` is still accepted as `read_write` during migration. If it's empty, DB keys still work (previously an empty setting rejected everything).
5. **Per-key throttling** (`api.throttling.ApiKeyRateThrottle`, a global DRF throttle class) uses the key's `throttle_rate` or `CIVICMIRROR_API_KEY_DEFAULT_RATE` (default `1000/hour`). Counters are keyed on the prefix and stored in the default cache, which is Redis in production. The legacy key and keyless endpoints aren't throttled by this class.
6. **Attribution:** `request.api_key` / `request.api_key_label` are set on every keyed request. The `api.access` logger records the prefix, method, and path for service-key requests, and rejected prefixed keys at `WARNING`. Secrets are never logged.
7. **Management:** Django admin (create, edit, deactivate; no delete) and the `create_api_key`, `revoke_api_key`, and `list_api_keys` management commands.

## Consequences

### Positive
- Each client can be revoked on its own, attributed, and rate-limited.
- The access level is enforced in one place, and new non-GET data endpoints are gated by `read_write` automatically.
- Public mock voting is unaffected: it stays behind user auth, not service scope.

### Negative / follow-ups
- One indexed DB lookup per request for non-legacy keys.
- **Legacy key retirement:** the FrontEnd should get its own `read` key (treated as public, since browser bundles are readable) and the MCP server its own secret key. Then the env-var fallback should be removed, which also invalidates the copy exposed in old FrontEnd builds.
- Public registration abuse is a separate concern (#202). Data-maintenance write endpoints don't exist yet (#203).

## Operations

- Issue: `python manage.py create_api_key --name "CivicData" --access read [--owner ...] [--expires YYYY-MM-DD] [--rate 500/hour]`
- Revoke: `python manage.py revoke_api_key cm_1a2b3c4d` (takes effect on the next request)
- List: `python manage.py list_api_keys [--all]`
- The migration must run **before** the new code takes traffic. See `docs/runbooks/production-deploy.md`.

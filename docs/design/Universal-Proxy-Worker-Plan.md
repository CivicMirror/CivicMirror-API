# Universal Cloudflare Proxy Worker — Implementation Plan

## Problem
GCP Cloud Run datacenter IPs are blocked by CloudFront/Akamai on multiple election result domains.
Confirmed blocked: `sos.iowa.gov` (Akamai), `www.enr-scvotes.org` (CloudFront).
Root cause for Election 77 failure: empty `current_ver.txt` response → JSONDecodeError.

## Architecture Decision
- Single universal CF Worker (`civicmirror-proxy`) — does NOT replace `ia-proxy` in-place (safer rollout/rollback)
- Shared backend utility `backend/core/http.py` — opt-in per call, never global
- Host-based proxy routing in Clarity adapter — NOT unconditional `use_proxy=True` (prevents proxying all Clarity states)
- `backend/core/` directory does not yet exist — must create it

---

## Phase 1: Cloudflare Worker (`cloudflare/civicmirror-proxy/`)

New worker, independent of `ia-proxy`. Improvements over existing worker:
- Domain allowlist covers SC ENR (both `www.enr-scvotes.org` AND `enr-scvotes.org`) + Iowa SOS + future Clarity hosts
- No Iowa-specific hardcoded headers (old worker has Iowa `Referer`/`Sec-Fetch-*` baked in)
- Supports GET **and HEAD** methods (IA SOS HEAD bypass was a bug in old worker gap)
- Response passthrough includes `ETag`, `Last-Modified`, `Location`, `Content-Type`, `Content-Length`
- `redirect: "manual"` — surfaces 3xx as explicit proxy error, doesn't silently follow
- `X-Proxy-Secret` stripped from forwarded headers; never logged; never forwarded upstream
- Hop-by-hop headers stripped

### Files
- `cloudflare/civicmirror-proxy/worker.js`
- `cloudflare/civicmirror-proxy/wrangler.toml`

### Initial allowlist
```
sos.iowa.gov
www.enr-scvotes.org
enr-scvotes.org
results.enr.clarityelections.com
```

### Error responses
- 401 — missing/invalid `X-Proxy-Secret`
- 403 — host not in allowlist  
- 502 — upstream fetch failed
- 400 — invalid/non-HTTPS target URL, disallowed method, 3xx from upstream (not silently followed)

---

## Phase 2: `backend/core/http.py` (new shared utility)

```python
def proxy_request(method: str, url: str, *, headers=None, use_proxy=False, timeout=30) -> requests.Response
def proxy_get(url: str, *, headers=None, use_proxy=False, timeout=30) -> requests.Response  # convenience
```

- `use_proxy=False` → direct `requests.request(method, url, ...)` (NOT `requests.get` — preserves HEAD)
- `use_proxy=True` + `CIVICMIRROR_PROXY_URL` set → routes through proxy with `X-Proxy-Secret`
- `use_proxy=True` + `CIVICMIRROR_PROXY_URL` not set → falls back to direct (local dev)
- Explicit error handling:
  - Proxy 401 → raise `ProxyAuthError`
  - Proxy 403 → raise `ProxyDomainNotAllowedError`  
  - Proxy 5xx → raise `ProxyUpstreamError`
  - Unexpected 3xx → raise `ProxyRedirectError`

### Settings in `base.py`
```python
CIVICMIRROR_PROXY_URL = env("CIVICMIRROR_PROXY_URL", default="")
CIVICMIRROR_PROXY_SECRET = env("CIVICMIRROR_PROXY_SECRET", default="")
# Deprecated — remove after IA SOS migration verified
IA_SOS_PROXY_URL = env("IA_SOS_PROXY_URL", default="")
IA_SOS_PROXY_SECRET = env("IA_SOS_PROXY_SECRET", default="")
```

---

## Phase 3: Adapter Updates

### `results/adapters/clarity.py`
- Host-based proxy routing — NOT unconditional:
  ```python
  CLARITY_PROXY_HOSTS = {"www.enr-scvotes.org", "enr-scvotes.org"}
  # ...
  use_proxy = urlparse(ver_url).hostname in CLARITY_PROXY_HOSTS
  response = proxy_get(ver_url, headers=_CLARITY_HEADERS, use_proxy=use_proxy)
  ```
- Both `requests.get()` calls (line 104 and 128) replaced with `proxy_get()`
- Other Clarity states (CO, WV) — no proxy unless their host is in `CLARITY_PROXY_HOSTS`

### `integrations/ia_sos/client.py`
- Replace custom `_get()` proxy logic with `proxy_request("GET", ..., use_proxy=True)`
- **Critical:** Replace `self._session.head(full_url, ...)` (line ~174) with `proxy_request("HEAD", ..., use_proxy=True)`
  - This was a confirmed bypass bug — HEAD always went direct, would fail from GCP
- Preserve ETag/Last-Modified header semantics — these come through the new worker's response passthrough
- Keep `IA_SOS_PROXY_URL` fallback temporarily during migration

---

## Phase 4: Deploy / Secrets

### GCP Secret Manager (manual step)
```
gcloud secrets create CIVICMIRROR_PROXY_URL --project civicmirror-2026
gcloud secrets create CIVICMIRROR_PROXY_SECRET --project civicmirror-2026
```

### Cloud Run service env
Update `.github/workflows/deploy.yml` (line ~241):
- Add `CIVICMIRROR_PROXY_URL` and `CIVICMIRROR_PROXY_SECRET` secret bindings
- Keep `IA_SOS_PROXY_URL` / `IA_SOS_PROXY_SECRET` bindings until IA migration verified

### Cloudflare deployment
```bash
cd cloudflare/civicmirror-proxy
wrangler deploy
wrangler secret put PROXY_SECRET
wrangler secret put ALLOWED_HOSTS  # comma-separated list
```

---

## Phase 5: Tests

### Update existing tests
- `backend/results/tests/test_clarity_adapter.py` — patch `core.http.proxy_get` instead of `requests.get`
- `backend/integrations/ia_sos/tests/test_client.py` — update proxy routing assertions; add HEAD-via-proxy mock

### New tests
- `backend/core/tests/test_http.py` — unit tests for `proxy_request()`:
  - Direct fallback when `CIVICMIRROR_PROXY_URL` not set
  - Proxy routing when configured
  - HEAD method passthrough
  - Error class mapping (401→ProxyAuthError, 403→ProxyDomainNotAllowedError, etc.)

---

## Deferred (out of scope for this PR — separate issues to track)

1. **`ingest_official_results` double-write** — no DB unique constraint on `OfficialResult` natural key; concurrent Celery retries can produce `MultipleObjectsReturned`. Needs: DB migration adding unique constraint + per-election Redis lock.

2. **IA candidate sync queueing race** — slow proxy calls can queue duplicate stage-2 tasks. Needs: "in-progress" lock per fingerprint.

3. **CO SOS, SC VREMS, VA ELECT block risk** — state/gov sites with no proxy, medium-high risk. Monitor; add to allowlist + proxy opt-in if blocked.

---

## Rollout Order
1. Deploy `civicmirror-proxy` CF Worker
2. Add GCP secrets
3. Deploy `backend/core/http.py` + settings changes  
4. Update adapters (clarity + ia_sos) + tests
5. Update `deploy.yml` + redeploy Cloud Run
6. Verify Election 77 ingest: `POST /internal/tasks/ingest-results/` for SC/77
7. Retire `ia-proxy` + `IA_SOS_PROXY_*` secrets once IA SOS verified working


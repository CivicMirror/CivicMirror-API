/**
 * CivicMirror Universal Proxy Worker
 *
 * Proxies GET and HEAD requests to allowlisted election data hosts from
 * Cloudflare edge IPs, bypassing GCP datacenter IP blocks (Akamai, CloudFront).
 *
 * Usage:
 *   GET  https://<worker-url>/?url=https%3A%2F%2Fsos.iowa.gov%2Fpath
 *   HEAD https://<worker-url>/?url=https%3A%2F%2Fsos.iowa.gov%2Fpath
 *   Header: X-Proxy-Secret: <PROXY_SECRET>
 *
 * Config (CF Worker Secrets):
 *   PROXY_SECRET   — shared secret with the Django backend
 *   ALLOWED_HOSTS  — comma-separated allowlist of target hostnames
 *                    e.g. "sos.iowa.gov,www.enr-scvotes.org,enr-scvotes.org,results.enr.clarityelections.com"
 *
 * Deploy:
 *   wrangler deploy
 *   wrangler secret put PROXY_SECRET
 *   wrangler secret put ALLOWED_HOSTS
 *
 * After deployment, add the worker URL to GCP Secret Manager:
 *   gcloud secrets versions add CIVICMIRROR_PROXY_URL \
 *     --data-file=<(echo -n "https://civicmirror-proxy.<subdomain>.workers.dev/")
 */

const ALLOWED_METHODS = new Set(["GET", "HEAD"]);

// Headers forwarded back to the caller from the upstream response.
const PASSTHROUGH_RESPONSE_HEADERS = [
  "Content-Type",
  "Content-Length",
  "ETag",
  "Last-Modified",
  "Location",
];

// Generic browser UA — sufficient to pass CDN bot checks from Cloudflare edge IPs.
// Intentionally minimal: no site-specific Referer or Sec-Fetch-* values.
const UPSTREAM_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  Accept: "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.5",
};

export default {
  async fetch(request, env) {
    // --- Auth ---------------------------------------------------------------
    const secret = request.headers.get("X-Proxy-Secret");
    if (!env.PROXY_SECRET || secret !== env.PROXY_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    // --- Method -------------------------------------------------------------
    const method = request.method;
    if (!ALLOWED_METHODS.has(method)) {
      return new Response(`Method ${method} not allowed`, { status: 405 });
    }

    // --- URL validation -----------------------------------------------------
    const reqUrl = new URL(request.url);
    const targetParam = reqUrl.searchParams.get("url");
    if (!targetParam) {
      return new Response("Missing ?url= parameter", { status: 400 });
    }

    let targetUrl;
    try {
      targetUrl = new URL(targetParam);
    } catch {
      return new Response("Invalid url parameter", { status: 400 });
    }

    if (targetUrl.protocol !== "https:") {
      return new Response("Only HTTPS targets are allowed", { status: 400 });
    }

    // --- Allowlist ----------------------------------------------------------
    const allowedHosts = (env.ALLOWED_HOSTS || "")
      .split(",")
      .map((h) => h.trim())
      .filter(Boolean);

    if (!allowedHosts.includes(targetUrl.hostname)) {
      return new Response(
        `Host ${targetUrl.hostname} is not in the proxy allowlist`,
        { status: 403 }
      );
    }

    // --- Upstream fetch -----------------------------------------------------
    let upstream;
    try {
      upstream = await fetch(targetUrl.toString(), {
        method,
        headers: UPSTREAM_HEADERS,
        redirect: "follow",
      });
    } catch (err) {
      return new Response(`Upstream fetch failed: ${err.message}`, {
        status: 502,
      });
    }

    // --- Response -----------------------------------------------------------
    const responseHeaders = new Headers();
    for (const header of PASSTHROUGH_RESPONSE_HEADERS) {
      const val = upstream.headers.get(header);
      if (val) responseHeaders.set(header, val);
    }
    responseHeaders.set("X-Upstream-Status", String(upstream.status));
    responseHeaders.set("X-Upstream-Url", upstream.url);

    // HEAD responses must not have a body per RFC 9110.
    const body = method === "HEAD" ? null : upstream.body;

    return new Response(body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  },
};

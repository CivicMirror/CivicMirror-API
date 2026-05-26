/**
 * CivicMirror — Cloudflare Worker: Iowa SOS PDF Proxy
 *
 * Routes requests to sos.iowa.gov from Cloudflare edge IPs to bypass
 * Akamai's GCP datacenter IP block (Layer 1 reputation filter).
 *
 * Usage:
 *   GET https://<worker-url>/?url=https%3A%2F%2Fsos.iowa.gov%2Fpath%2Fto%2Ffile.pdf
 *   Header: X-Proxy-Secret: <PROXY_SECRET>
 *
 * Config:
 *   PROXY_SECRET — set in CF Worker Secrets (dashboard → Worker → Settings → Variables → Secrets)
 *
 * Deploy:
 *   wrangler deploy
 *   wrangler secret put PROXY_SECRET
 */

const ALLOWED_HOST = "sos.iowa.gov";

const BROWSER_HEADERS = {
  "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
  Accept:
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.5",
  Referer: "https://sos.iowa.gov/elections-voting",
  "Sec-Fetch-Dest": "document",
  "Sec-Fetch-Mode": "navigate",
  "Sec-Fetch-Site": "same-origin",
};

export default {
  async fetch(request, env) {
    const secret = request.headers.get("X-Proxy-Secret");
    if (!env.PROXY_SECRET || secret !== env.PROXY_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    const reqUrl = new URL(request.url);
    const targetUrl = reqUrl.searchParams.get("url");

    if (!targetUrl) {
      return new Response("Missing ?url= parameter", { status: 400 });
    }

    let parsedTarget;
    try {
      parsedTarget = new URL(targetUrl);
    } catch {
      return new Response("Invalid url parameter", { status: 400 });
    }

    if (parsedTarget.hostname !== ALLOWED_HOST) {
      return new Response(`Only ${ALLOWED_HOST} is proxied`, { status: 403 });
    }

    const upstream = await fetch(targetUrl, { headers: BROWSER_HEADERS });

    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type":
          upstream.headers.get("Content-Type") || "application/octet-stream",
        "X-Upstream-Status": String(upstream.status),
      },
    });
  },
};

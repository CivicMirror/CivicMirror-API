/**
 * CivicMirror — Cloudflare Worker: Iowa SOS PDF Proxy Test
 *
 * Purpose: Proxy requests to sos.iowa.gov from Cloudflare edge IPs to
 * bypass Akamai's GCP datacenter IP block (Layer 1 reputation filter).
 *
 * Deployed at: https://square-sun-2813.welefort.workers.dev/
 *
 * Test with:
 *   curl -s -o /dev/null -w "%{http_code} %{size_download}b" \
 *     -H "X-Proxy-Secret: civicmirror-test-123" \
 *     https://square-sun-2813.welefort.workers.dev/
 *
 * Expected: 200, ~220000 bytes (the cal3yr.pdf)
 *
 * NOTE: This is a TEST script only. If confirmed working, the production
 * version will use a strong secret stored in Cloudflare Worker Secrets
 * (not hardcoded) and will accept the target URL as a parameter.
 */

export default {
  async fetch(request) {
    const secret = request.headers.get("X-Proxy-Secret");
    if (secret !== "civicmirror-test-123") {
      return new Response("Unauthorized", { status: 401 });
    }

    const target = "https://sos.iowa.gov/elections/pdf/cal3yr.pdf";

    const resp = await fetch(target, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        Accept:
          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        Referer: "https://sos.iowa.gov/elections-voting",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
      },
    });

    return new Response(resp.body, {
      status: resp.status,
      headers: {
        "Content-Type":
          resp.headers.get("Content-Type") || "application/pdf",
        "X-Upstream-Status": String(resp.status),
      },
    });
  },
};

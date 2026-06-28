"""
CivicMirror CF Solver — FastAPI microservice.

Accepts a target URL, launches a nodriver Chrome browser via Xvfb, waits for
Cloudflare's Managed Challenge to auto-resolve, then optionally fetches a
payload URL from within the browser session (using its live cookie jar, which
includes HttpOnly cookies that can't be extracted via document.cookie or CDP).

Two operation modes:
  1. Cookie-return mode (payload_url omitted): solves CF challenge and returns
     whatever cookies are readable via document.cookie. Only non-HttpOnly
     cookies are returned.
  2. In-browser-fetch mode (payload_url provided): after the challenge resolves,
     executes a JavaScript fetch() for payload_url using credentials:'include',
     which automatically includes all cookies (including HttpOnly ones such as
     cf_clearance and APEX session cookies). Returns the response text as
     payload_text. This is the recommended mode for CF-protected endpoints
     where cookies are HttpOnly.

Proxy support: set CF_PROXY_URL env var (e.g. http://user:pass@host:port) to
route Chrome's traffic through a residential proxy. Required in Cloud Run
(GCP datacenter IPs fail Cloudflare Bot Management; residential IPs pass).

Deploy with:
    docker build -t civicmirror-cf-solver .
    docker run --rm -p 8080:8080 --shm-size=2g \\
        -e CF_SOLVER_SECRET=<secret> \\
        -e CF_PROXY_URL=http://user:pass@proxy:port \\
        civicmirror-cf-solver
"""
import asyncio
import json
import logging
import os
import socket
import subprocess
import time
import urllib.request
from typing import Optional

import nodriver as uc
import nodriver.cdp.runtime as crt
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CivicMirror CF Solver")

try:
    _chrome_version = subprocess.check_output(
        ["/usr/bin/google-chrome", "--version"], stderr=subprocess.DEVNULL
    ).decode().strip()
    logger.info("cf_solver.chrome_build %s", _chrome_version)
except Exception:
    logger.warning("cf_solver.chrome_build_unknown")

# Prevent concurrent Chrome launches — each session uses ~500MB RAM.
_browser_lock = asyncio.Lock()

CF_SOLVER_SECRET = os.environ.get("CF_SOLVER_SECRET", "")
CF_PROXY_URL = os.environ.get("CF_PROXY_URL", "")  # e.g. http://user:pass@host:port

_CHROME_LAUNCH_ARGS = [
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-service-autorun",
    "--no-default-browser-check",
    "--homepage=about:blank",
    "--no-pings",
    "--password-store=basic",
    "--disable-infobars",
    "--disable-breakpad",
    "--disable-dev-shm-usage",
    "--disable-session-crashed-bubble",
    "--disable-search-engine-choice-screen",
    "--disable-features=IsolateOrigins,site-per-process",
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--lang=en-US",
]

if CF_PROXY_URL:
    _CHROME_LAUNCH_ARGS.append(f"--proxy-server={CF_PROXY_URL}")
    logger.info("cf_solver.proxy_enabled url=%s", CF_PROXY_URL)


def _check_auth(x_cf_solver_secret: str):
    if not CF_SOLVER_SECRET:
        return
    if x_cf_solver_secret != CF_SOLVER_SECRET:
        raise HTTPException(status_code=401, detail="Invalid CF-Solver-Secret")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _start_chrome() -> tuple[subprocess.Popen, int]:
    """Spawn Chrome with a known debug port and wait up to 30s for it to be ready."""
    port = _free_port()
    user_data_dir = f"/tmp/uc_{os.getpid()}_{port}"

    proc = subprocess.Popen(
        [
            "/usr/bin/google-chrome",
            f"--remote-debugging-port={port}",
            "--remote-debugging-host=127.0.0.1",
            f"--user-data-dir={user_data_dir}",
        ] + _CHROME_LAUNCH_ARGS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("cf_solver.chrome_spawned pid=%d port=%d", proc.pid, port)

    version_url = f"http://127.0.0.1:{port}/json/version"
    start = time.monotonic()
    deadline = start + 30.0
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Chrome exited early (code={proc.returncode})")
        try:
            urllib.request.urlopen(version_url, timeout=1)
            elapsed = time.monotonic() - start
            logger.info("cf_solver.chrome_ready port=%d pid=%d elapsed=%.2fs", port, proc.pid, elapsed)
            return proc, port
        except Exception:
            await asyncio.sleep(0.3)

    proc.kill()
    raise RuntimeError(f"Chrome (pid={proc.pid}) did not open debug port {port} within 30s")


class SolveRequest(BaseModel):
    url: str
    wait_seconds: int = 15
    payload_url: Optional[str] = None  # if set, fetch this URL in-browser after challenge
    payload_referer: Optional[str] = None  # Referer for payload fetch (defaults to url)


class SolveResponse(BaseModel):
    cookies: dict[str, str]  # non-HttpOnly cookies from document.cookie (may be empty)
    user_agent: str
    payload_text: Optional[str] = None  # set when payload_url was provided


@app.post("/solve", response_model=SolveResponse)
async def solve(
    req: SolveRequest,
    x_cf_solver_secret: str = Header(default=""),
):
    _check_auth(x_cf_solver_secret)

    async with _browser_lock:
        logger.info(
            "cf_solver.solve url=%s wait=%ds payload_url=%s",
            req.url, req.wait_seconds, req.payload_url or "(none)",
        )

        proc = None
        browser = None
        try:
            proc, port = await _start_chrome()

            browser = await uc.start(
                host="127.0.0.1",
                port=port,
                no_sandbox=True,
                lang="en-US",
            )

            page = await browser.get(req.url)
            await page.sleep(req.wait_seconds)

            title = await page.evaluate("document.title", return_by_value=True)
            webdriver_flag = await page.evaluate("navigator.webdriver", return_by_value=True)
            logger.info("cf_solver.solve page_title=%r navigator.webdriver=%r", title, webdriver_flag)

            if "just a moment" in title.lower():
                raise HTTPException(
                    status_code=502,
                    detail=f"CF challenge not resolved after {req.wait_seconds}s — title={title!r}",
                )

            # Read whatever cookies are visible from JS (non-HttpOnly only).
            cookie_str = await page.evaluate("document.cookie", return_by_value=True)
            ua = await page.evaluate("navigator.userAgent", return_by_value=True)
            cookies: dict[str, str] = {}
            for pair in (cookie_str or "").split(";"):
                pair = pair.strip()
                if "=" in pair:
                    name, _, value = pair.partition("=")
                    cookies[name.strip()] = value.strip()
            logger.info("cf_solver.solve cookie_keys=%s", list(cookies.keys()))

            # In-browser fetch mode: use Chrome's live cookie jar (includes HttpOnly)
            # to fetch the payload URL. This bypasses the need to extract cookies.
            payload_text: Optional[str] = None
            if req.payload_url:
                referer = req.payload_referer or req.url

                # Synchronous XHR — avoids async/Promise complications.
                # nodriver's page.evaluate() has a bug with dict return values;
                # use page.send(cdp.runtime.evaluate(...)) to get the raw RemoteObject.
                fetch_js = f"""
(function() {{
    try {{
        const xhr = new XMLHttpRequest();
        xhr.open('GET', {json.dumps(req.payload_url)}, false);
        xhr.withCredentials = true;
        xhr.setRequestHeader('Referer', {json.dumps(referer)});
        xhr.send(null);
        return {{ status: xhr.status, text: xhr.responseText, ct: xhr.getResponseHeader('content-type') || '' }};
    }} catch(e) {{
        return {{ error: e.toString() }};
    }}
}})()
"""
                remote_obj, errors = await page.send(
                    crt.evaluate(
                        expression=fetch_js,
                        return_by_value=True,
                        user_gesture=True,
                        allow_unsafe_eval_blocked_by_csp=True,
                    )
                )
                fetch_result: dict = (remote_obj.value if remote_obj else None) or {}
                logger.info("cf_solver.payload_fetch status=%s len=%s", fetch_result.get("status"), len(fetch_result.get("text") or ""))

                if "error" in fetch_result:
                    raise HTTPException(
                        status_code=502,
                        detail=f"In-browser XHR failed: {fetch_result['error']}",
                    )
                if not fetch_result or fetch_result.get("status") != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Payload URL returned HTTP {fetch_result.get('status')}: {str(fetch_result.get('text', ''))[:200]}",
                    )
                payload_text = fetch_result.get("text") or ""
                logger.info(
                    "cf_solver.payload_fetch_ok bytes=%d ct=%s",
                    len(payload_text),
                    fetch_result.get("ct", ""),
                )

            logger.info(
                "cf_solver.solve success cf_clearance=%s payload=%s url=%s",
                "yes" if "cf_clearance" in cookies else "no",
                f"{len(payload_text)}B" if payload_text else "none",
                req.url,
            )
            return SolveResponse(cookies=cookies, user_agent=ua, payload_text=payload_text)
        finally:
            if browser:
                browser.stop()
            if proc and proc.poll() is None:
                proc.kill()
                proc.wait()


@app.get("/health")
async def health():
    return {"status": "ok"}

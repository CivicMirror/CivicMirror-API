"""
CivicMirror CF Solver — FastAPI microservice.

Accepts a target URL, launches a nodriver Chrome browser via Xvfb, waits for
Cloudflare's Managed Challenge to auto-resolve, and returns all browser cookies
plus the User-Agent string. The caller can then use those cookies for subsequent
plain httpx requests without triggering the CF challenge again.

Designed for CF Managed Challenge (cType='managed') which requires real browser
JS execution but no human checkbox interaction. Not designed for Turnstile
interactive challenges.

Deploy with:
    docker build -t civicmirror-cf-solver .
    docker run --rm -p 8080:8080 --shm-size=2g \
        -e CF_SOLVER_SECRET=<secret> civicmirror-cf-solver
"""
import asyncio
import logging
import os

import nodriver as uc
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="CivicMirror CF Solver")

# Prevent concurrent Chrome launches — each session uses ~500MB RAM.
_browser_lock = asyncio.Lock()

CF_SOLVER_SECRET = os.environ.get("CF_SOLVER_SECRET", "")


def _check_auth(x_cf_solver_secret: str):
    if not CF_SOLVER_SECRET:
        return
    if x_cf_solver_secret != CF_SOLVER_SECRET:
        raise HTTPException(status_code=401, detail="Invalid CF-Solver-Secret")


class SolveRequest(BaseModel):
    url: str
    wait_seconds: int = 20


class SolveResponse(BaseModel):
    cookies: dict[str, str]
    user_agent: str


@app.post("/solve", response_model=SolveResponse)
async def solve(
    req: SolveRequest,
    x_cf_solver_secret: str = Header(default=""),
):
    _check_auth(x_cf_solver_secret)

    async with _browser_lock:
        logger.info("cf_solver.solve url=%s wait=%ds", req.url, req.wait_seconds)
        browser = await uc.start(headless=False, lang="en-US")
        try:
            page = await browser.get(req.url)
            await page.sleep(req.wait_seconds)

            title = await page.evaluate("document.title")
            logger.info("cf_solver.solve page_title=%r", title)

            if "just a moment" in title.lower():
                raise HTTPException(
                    status_code=502,
                    detail=f"CF challenge not resolved after {req.wait_seconds}s — title={title!r}",
                )

            all_cookies = await browser.cookies.get_all()
            cookies = {c.name: c.value for c in all_cookies}
            ua = browser.info.get("User-Agent", "")

            logger.info(
                "cf_solver.solve success cf_clearance=%s url=%s",
                "yes" if "cf_clearance" in cookies else "no",
                req.url,
            )
            return SolveResponse(cookies=cookies, user_agent=ua)
        finally:
            browser.stop()


@app.get("/health")
async def health():
    return {"status": "ok"}

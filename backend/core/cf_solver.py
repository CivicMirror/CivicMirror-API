"""
Client for the CivicMirror CF Solver microservice.

The CF Solver is a separate Docker container (cloudflare/cf-solver/) that runs
nodriver + Xvfb to bypass Cloudflare Bot Management (cType='managed'). This
client calls it and caches the returned cf_clearance cookie per domain in Redis
so adapters don't launch a new Chrome session for every request.

Usage:
    from core.cf_solver import CfSolverClient, CfSolverError

    client = CfSolverClient()
    result = client.get_cookies("https://www6.ohiosos.gov/ords/f?p=CFDISCLOSURE:73:::NO::")
    # result = {"cookies": {"cf_clearance": "...", "ORA_WWV_APP_119": "..."}, "user_agent": "..."}

    # Then use cookie_header for subsequent requests:
    cookie_header = "; ".join(f"{k}={v}" for k, v in result["cookies"].items())
    httpx.get(url, headers={"Cookie": cookie_header, "User-Agent": result["user_agent"]})
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Redis TTL for cached CF cookies — slightly under cf_clearance's typical 30-min validity.
_COOKIE_CACHE_TTL = 25 * 60  # 25 minutes
_CACHE_KEY_PREFIX = "cf_solver:cookies:"


class CfSolverError(Exception):
    """CF solver request failed."""


class CfSolverUnavailableError(CfSolverError):
    """CF_SOLVER_URL is not configured — solver cannot be called."""


def _cache_key(domain: str) -> str:
    return f"{_CACHE_KEY_PREFIX}{domain}"


class CfSolverClient:
    """
    Calls the CF solver service to obtain CF-bypass cookies for a given domain.

    Caches results in Redis for 25 minutes so that a single nodriver Chrome
    session covers many requests to the same host within that window.
    """

    def __init__(self, wait_seconds: int = 20, timeout: int = 90):
        self.wait_seconds = wait_seconds
        self.timeout = timeout

    @property
    def _solver_url(self) -> str:
        return (getattr(settings, "CF_SOLVER_URL", "") or "").rstrip("/")

    @property
    def _solver_secret(self) -> str:
        return getattr(settings, "CF_SOLVER_SECRET", "") or ""

    def get_cookies(self, url: str) -> dict:
        """
        Return CF bypass cookies for the domain of *url*.

        First checks Redis for a cached result. On cache miss, calls the CF
        solver service (which launches Chrome + Xvfb), caches the result, and
        returns it.

        Returns:
            {"cookies": {name: value, ...}, "user_agent": "Mozilla/5.0 ..."}

        Raises:
            CfSolverUnavailableError: CF_SOLVER_URL not configured.
            CfSolverError: Solver returned an error or Chrome couldn't bypass CF.
        """
        if not self._solver_url:
            raise CfSolverUnavailableError(
                "CF_SOLVER_URL is not configured — cannot bypass CF Bot Management. "
                "Deploy the cf-solver service and set CF_SOLVER_URL in settings."
            )

        domain = urlparse(url).hostname or url
        cache_key = _cache_key(domain)
        cached = cache.get(cache_key)
        if cached:
            logger.debug("cf_solver.cache_hit domain=%s", domain)
            return cached

        logger.info("cf_solver.solve_start url=%s", url)
        try:
            resp = requests.post(
                f"{self._solver_url}/solve",
                json={"url": url, "wait_seconds": self.wait_seconds},
                headers={"X-CF-Solver-Secret": self._solver_secret},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise CfSolverError(f"CF solver request failed: {exc}") from exc

        if resp.status_code == 401:
            raise CfSolverError("CF solver returned 401 — check CF_SOLVER_SECRET")
        if not resp.ok:
            raise CfSolverError(
                f"CF solver returned HTTP {resp.status_code}: {resp.text[:200]}"
            )

        result = resp.json()
        cache.set(cache_key, result, _COOKIE_CACHE_TTL)
        logger.info(
            "cf_solver.solve_complete domain=%s cookies=%s",
            domain,
            list(result.get("cookies", {}).keys()),
        )
        return result

    def cookie_header(self, url: str) -> tuple[str, str]:
        """
        Convenience: returns (cookie_header_value, user_agent) ready for use in
        requests headers. Calls get_cookies() internally.
        """
        result = self.get_cookies(url)
        header = "; ".join(f"{k}={v}" for k, v in result["cookies"].items())
        return header, result.get("user_agent", "")

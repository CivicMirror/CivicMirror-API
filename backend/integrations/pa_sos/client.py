"""
HTTP client for pavoterservices.beta.pa.gov using Playwright and Stealth.
Requires passing WAF challenge via BasicSearch.aspx, then loading ElectionInfo.aspx
to extract candidate listing JSON from the hidden input #dataJson.
"""
from __future__ import annotations

import logging
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .exceptions import PaSosError, PaSosRetryableError

logger = logging.getLogger(__name__)


class PaSosClient:
    def __init__(self, base_url: str = "https://www.pavoterservices.beta.pa.gov", timeout_ms: int = 60000):
        self.base_url = base_url
        self.timeout_ms = timeout_ms
        self._playwright_ctx = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self) -> PaSosClient:
        try:
            self._playwright_ctx = Stealth().use_sync(sync_playwright())
            self._playwright = self._playwright_ctx.__enter__()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                ]
            )
            self._context = self._browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            self._page = self._context.new_page()
            return self
        except Exception as exc:
            self.__exit__(type(exc), exc, exc.__traceback__)
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright_ctx:
            try:
                self._playwright_ctx.__exit__(exc_type, exc_val, exc_tb)
            except Exception:
                pass

    def fetch_candidate_list(self, election_id: int = 153) -> str:
        """
        Fetch the hidden #dataJson field value from ElectionInfo.aspx.
        Navigates to BasicSearch.aspx first to trigger and pass the WAF cookies.
        """
        try:
            # 1. Pass WAF challenge on BasicSearch
            search_url = f"{self.base_url}/electioninfo/BasicSearch.aspx"
            logger.info("Navigating to %s to pass WAF challenge", search_url)
            self._page.goto(search_url, timeout=self.timeout_ms)
            self._page.wait_for_load_state("networkidle", timeout=self.timeout_ms)

            # 2. Go to ElectionInfo
            info_url = f"{self.base_url}/electioninfo/ElectionInfo.aspx"
            logger.info("Navigating to %s", info_url)
            self._page.goto(info_url, timeout=self.timeout_ms)
            self._page.wait_for_load_state("networkidle", timeout=self.timeout_ms)

            # 3. Check selected election in dropdown and select if needed
            dropdown_selector = "#ctl00_ContentPlaceHolder1_ReportElectionDropDown"
            selected_val = self._page.locator(dropdown_selector).evaluate("el => el.value")

            if not selected_val:
                raise PaSosError("ReportElectionDropDown not found or has no value")

            if int(selected_val) != election_id:
                logger.info("Selecting election_id %d (currently %s)", election_id, selected_val)
                self._page.select_option(dropdown_selector, value=str(election_id))
                self._page.wait_for_load_state("networkidle", timeout=self.timeout_ms)

            # 4. Extract dataJson input value
            data_json = self._page.locator("#dataJson").get_attribute("value")
            if not data_json:
                raise PaSosError("dataJson input value is empty or missing")
            return data_json

        except Exception as exc:
            raise PaSosRetryableError(f"Failed to fetch candidate list for election {election_id}: {exc}") from exc

    def fetch_candidate_detail(self, candidate_id: int) -> str:
        """Fetch candidate detail page HTML by ID."""
        try:
            detail_url = f"{self.base_url}/ElectionInfo/CandidateInfo.aspx?ID={candidate_id}"
            logger.info("Navigating to candidate detail: %s", detail_url)
            self._page.goto(detail_url, timeout=self.timeout_ms)
            self._page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            return self._page.content()
        except Exception as exc:
            raise PaSosRetryableError(f"Failed to fetch candidate detail for ID {candidate_id}: {exc}") from exc

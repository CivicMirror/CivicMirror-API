"""
Browser client for elections.alaska.gov/election-candidates/ (Alaska's
candidate-filing listing), using Playwright + Stealth.

The page is a WordPress site built on Formidable Forms Pro: the visible
"Search Candidates" form submits via AJAX to wp-admin/admin-ajax.php
(action=frm_entries_create), carrying a per-page-load nonce, an
antispam_token, and an opaque frm_state blob, plus several hidden
item_meta[...] fields that the page's own JS populates on the Election
select's change event. Replicating that by hand with plain HTTP requests
would mean tracking those tokens and whatever internal election/contest ID
mapping the hidden fields encode -- fragile, and liable to break silently on
any Formidable/WP update. Driving a real browser avoids all of that: we
just use the form the way a visitor does.

Separately, www.elections.alaska.gov sends an incomplete TLS chain (see
results/adapters/ak.py's module docstring and issue #233) -- irrelevant
here, since real Chromium (unlike `requests`) chases the leaf's AIA "CA
Issuers" URL on its own, the same way a visitor's browser does.

Confirmed live 2026-11-03: the "Contest" field is mandatory (submitting
without one fails validation and the page just redisplays its default
view), and there is no "All" option for it -- callers must loop over each
contest name they want (see mappers.CONTESTS_IN_SCOPE) and issue one search
per contest. "District" defaults to "All" and does not need to be touched.
"""
from __future__ import annotations

import logging

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from .exceptions import AkSosError, AkSosRetryableError

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.elections.alaska.gov/election-candidates/"

_FORM_SELECTOR = "#form_searchcandidatesform3"
_ELECTION_SELECT = "#field_stebs3"
_CONTEST_SELECT = "#field_cx3x52"
_SUBMIT_BUTTON = f"{_FORM_SELECTOR} button[type='submit']"
_RESULTS_SELECTOR = "article"

_NAV_RETRY_ATTEMPTS = 3


class AkSosClient:
    def __init__(self, timeout_ms: int = 30000):
        self.timeout_ms = timeout_ms
        self._playwright_ctx = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self) -> AkSosClient:
        try:
            self._playwright_ctx = Stealth().use_sync(sync_playwright())
            self._playwright = self._playwright_ctx.__enter__()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            self._context = self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
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

    def _goto_candidates_page(self) -> None:
        for attempt in range(1, _NAV_RETRY_ATTEMPTS + 1):
            try:
                self._page.goto(_BASE_URL, timeout=self.timeout_ms)
                self._page.wait_for_selector(_ELECTION_SELECT, timeout=self.timeout_ms)
                return
            except Exception as exc:
                logger.warning(
                    "ak_sos.client.goto_failed attempt=%d/%d err=%s",
                    attempt, _NAV_RETRY_ATTEMPTS, exc,
                )
        raise AkSosRetryableError(f"could not load {_BASE_URL} after {_NAV_RETRY_ATTEMPTS} attempts")

    def fetch_candidates_html(self, election_name: str, contest_name: str) -> str:
        """
        Search the candidate listing for one (election, contest) pair and
        return the resulting page HTML (District left at its "All" default).

        Each call re-navigates to the page fresh rather than re-using a
        previous search's DOM state, trading a bit of speed for not having
        to reason about whether the AJAX-updated DOM left some stale hidden
        field behind from the prior contest's selection.
        """
        try:
            self._goto_candidates_page()

            self._page.locator(_ELECTION_SELECT).select_option(label=election_name)
            # Selecting Election triggers the page's own AJAX lookup that populates
            # hidden fields keyed off it (confirmed live: item_meta[1173]/[1174]/[1175]).
            # Selecting Contest before that round trip finishes submits with those
            # hidden fields still empty/stale, which the server reports back as a
            # generic validation failure rather than anything that names the real cause.
            self._page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
            self._page.locator(_CONTEST_SELECT).select_option(label=contest_name)
            self._page.locator(_SUBMIT_BUTTON).click()
            self._page.wait_for_load_state("networkidle", timeout=self.timeout_ms)

            html = self._page.locator(_RESULTS_SELECTOR).first.inner_html()
            # Every per-field "X cannot be blank." message is always present in the DOM
            # as a hidden template (confirmed live: it's in the markup even on a fresh,
            # un-submitted page load), so checking for those strings is a false-positive
            # trap. The banner Formidable actually renders on a real validation failure
            # is this one, visible only then.
            if "problem with your submission" in html:
                raise AkSosError(
                    f"search form validation failed for election={election_name!r} "
                    f"contest={contest_name!r} -- selector/option text may be stale"
                )
            return html
        except AkSosError:
            raise
        except Exception as exc:
            raise AkSosRetryableError(
                f"fetch_candidates_html failed for election={election_name!r} contest={contest_name!r}: {exc}"
            ) from exc

"""
Missouri (MO) results adapter — Missouri Secretary of State.

Source: https://www.sos.mo.gov/CMSImages/ElectionResultsStatistics/{filename}.pdf
Access: Public HTTPS. Cloudflare-fronted — a realistic browser User-Agent
        header is REQUIRED (confirmed via direct testing 2026-07-21; see
        docs/state-research/MO/MO-Election_Research_UpdatedV2.md), otherwise
        the request gets a 403 Cloudflare challenge page instead of the PDF.
Schema: text-based (not scanned) PDF, "Grand Totals" report — one repeated
        block per contest. See mo_parse.py for the parsing logic.

Scope (this build): statewide top-of-ticket offices on the historical
Nov 5, 2024 general election only — "U.S. President and Vice President",
"U.S. Senator", "Governor", "Lieutenant Governor". District-level races,
judicial retention, and ballot measures/constitutional amendments are
follow-up work (need contest-type classification the current build
sidesteps — see the plan's "Follow-up work" section).

Cycle URL resolution: hardcoded to the 2024 general election's known PDF
URL for this historical POC. Live discovery of the current cycle's PDF
URL/filename for future elections is out of scope — see the plan's
"Follow-up work" section.

Because the URL is pinned to one cycle, fetch_results refuses any election
whose date is not Nov 5, 2024 (_SUPPORTED_ELECTION_DATE). Without that guard
the adapter served certified 2024 rows — President, U.S. Senator, Governor,
Lieutenant Governor — under whatever election id it was handed, including the
Nov 3, 2026 general. When live cycle discovery lands, replace the guard with
real URL resolution rather than widening it.
"""
from __future__ import annotations

import datetime
import hashlib
import io
import logging

import pdfplumber
import requests
from django.core.cache import cache

from .base import AdapterResult, StateResultsAdapter
from .mo_parse import parse_grand_totals_text
from .registry import register

logger = logging.getLogger(__name__)

_CACHE_TTL = 86400 * 30  # 30 days
_OFFICE_ALLOWLIST = frozenset({
    "U.S. President and Vice President", "U.S. Senator", "Governor", "Lieutenant Governor",
})
_GRAND_TOTALS_URL = "https://www.sos.mo.gov/CMSImages/ElectionResultsStatistics/2024GeneralElection.pdf"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_PDF_MAGIC_BYTES = b"%PDF"
# The one cycle _GRAND_TOTALS_URL actually describes.
_SUPPORTED_ELECTION_DATE = datetime.date(2024, 11, 5)


class MoSosError(Exception):
    """Non-retryable Missouri SOS integration error."""


class MoSosRetryableError(MoSosError):
    """Transient error that warrants a retry (network/CF-challenge/non-PDF response)."""


@register
class MissouriAdapter(StateResultsAdapter):
    state = "MO"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"mo_sos:checksum:{election_id}"

    def _fetch_grand_totals_pdf_bytes(self, url: str) -> bytes:
        try:
            response = requests.get(url, headers={"User-Agent": _BROWSER_USER_AGENT}, timeout=30)
        except requests.RequestException as exc:
            raise MoSosRetryableError(f"MO SOS GET failed: {exc}") from exc

        if response.status_code != 200 or not response.content.startswith(_PDF_MAGIC_BYTES):
            raise MoSosRetryableError(
                f"MO SOS did not return a PDF (status={response.status_code}) for url={url}"
            )

        return response.content

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        if isinstance(election_date, str):
            try:
                election_date = datetime.date.fromisoformat(election_date)
            except ValueError:
                election_date = None
        if election_date != _SUPPORTED_ELECTION_DATE:
            logger.warning(
                "mo_sos.adapter.unsupported_cycle election=%s date=%s supported=%s",
                election_id, election_date, _SUPPORTED_ELECTION_DATE,
            )
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=(
                    f"MO adapter only covers the {_SUPPORTED_ELECTION_DATE} general election; "
                    f"election {election_id} is dated {election_date}"
                ),
            )

        try:
            Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("mo_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        try:
            pdf_bytes = self._fetch_grand_totals_pdf_bytes(_GRAND_TOTALS_URL)
        except MoSosRetryableError as exc:
            logger.warning("mo_sos.adapter.pdf_fetch_failed err=%s", exc)
            return AdapterResult(
                rows=[], source_url=_GRAND_TOTALS_URL, mapping_confidence="none",
                notes=f"Failed to fetch Grand Totals PDF for election {election_id}",
            )

        checksum = hashlib.md5(pdf_bytes).hexdigest()
        cache_key = self.version_cache_key(election_id)
        if cache.get(cache_key) == checksum:
            return AdapterResult(
                rows=[], source_url=_GRAND_TOTALS_URL, mapping_confidence="full",
                unchanged=True, source_version=checksum,
            )

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        rows = parse_grand_totals_text(text, office_allowlist=_OFFICE_ALLOWLIST)

        if not rows:
            return AdapterResult(
                rows=[], source_url=_GRAND_TOTALS_URL, mapping_confidence="none",
                notes=f"No statewide contest rows parsed for election {election_id}",
            )

        return AdapterResult(
            rows=rows,
            source_url=_GRAND_TOTALS_URL,
            mapping_confidence="full",
            source_version=checksum,
        )

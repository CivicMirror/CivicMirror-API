"""
NC State Board of Elections — S3 bucket client.

Public bucket: https://s3.amazonaws.com/dl.ncsbe.gov
No authentication required.

Election results ZIPs live at:
  ENRS/{YYYY_MM_DD}/results_pct_{YYYYMMDD}.zip

Election discovery uses the S3 ListObjectsV2 API with prefix="ENRS/" and
delimiter="/" to enumerate per-election subdirectory prefixes.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

import requests

from .exceptions import NcSbeRetryableError

_S3_BASE = "https://s3.amazonaws.com/dl.ncsbe.gov"
_ENRS_PREFIX = "ENRS/"
_S3_NS = "http://s3.amazonaws.com/doc/2006-03-01/"
_TIMEOUT_LIST = 30
_TIMEOUT_HEAD = 15
_TIMEOUT_ZIP = 120
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Matches ENRS/YYYY_MM_DD/ subdirectory prefixes returned by the S3 listing.
_FOLDER_RE = re.compile(r"^ENRS/(\d{4}_\d{2}_\d{2})/$")


class NcSbeClient:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (compatible; CivicMirror/1.0; +https://civicmirror.welshrd.com)"
        )

    def _get(self, url: str, params: dict | None = None, timeout: int = _TIMEOUT_LIST) -> requests.Response:
        try:
            resp = self._session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            raise NcSbeRetryableError(f"NC SBE GET failed: {exc}") from exc
        if resp.status_code in _RETRYABLE_STATUSES:
            raise NcSbeRetryableError(f"NC SBE returned {resp.status_code} for {url}")
        resp.raise_for_status()
        return resp

    def list_election_date_strs(self) -> list[str]:
        """
        Return all YYYY_MM_DD strings from the ENRS/ prefix listing.
        Handles S3 pagination via ContinuationToken.
        """
        date_strs: list[str] = []
        params: dict = {
            "list-type": "2",
            "prefix": _ENRS_PREFIX,
            "delimiter": "/",
            "max-keys": "1000",
        }
        while True:
            resp = self._get(_S3_BASE, params=params)
            root = ET.fromstring(resp.content)
            for cp in root.findall(f"{{{_S3_NS}}}CommonPrefixes"):
                prefix_text = cp.findtext(f"{{{_S3_NS}}}Prefix") or ""
                m = _FOLDER_RE.match(prefix_text)
                if m:
                    date_strs.append(m.group(1))

            is_truncated = (root.findtext(f"{{{_S3_NS}}}IsTruncated") or "").lower() == "true"
            if not is_truncated:
                break
            token = root.findtext(f"{{{_S3_NS}}}NextContinuationToken")
            if not token:
                break
            params = {**params, "continuation-token": token}

        return sorted(date_strs)

    def fetch_results_etag(self, date_str: str) -> str | None:
        """HEAD request to get ETag for version detection. Returns None on 404."""
        url = _results_zip_url(date_str)
        try:
            resp = self._session.head(url, timeout=_TIMEOUT_HEAD)
            if resp.status_code == 404:
                return None
            if resp.status_code in _RETRYABLE_STATUSES:
                raise NcSbeRetryableError(f"NC SBE HEAD returned {resp.status_code} for {url}")
            resp.raise_for_status()
            return resp.headers.get("ETag", "").strip('"')
        except requests.RequestException as exc:
            raise NcSbeRetryableError(f"NC SBE HEAD failed: {exc}") from exc

    def fetch_results_zip(self, date_str: str) -> bytes:
        """Download and return the full results ZIP for a given election date."""
        url = _results_zip_url(date_str)
        try:
            resp = self._get(url, timeout=_TIMEOUT_ZIP)
        except requests.RequestException as exc:
            raise NcSbeRetryableError(f"NC SBE ZIP fetch failed: {exc}") from exc
        return resp.content


def _results_zip_url(date_str: str) -> str:
    """Build the S3 URL for a results ZIP from a YYYY_MM_DD date string."""
    compact = date_str.replace("_", "")
    return f"{_S3_BASE}/{_ENRS_PREFIX}{date_str}/results_pct_{compact}.zip"


def parse_results_tsv(zip_bytes: bytes) -> list[dict]:
    """
    Parse a results ZIP and return a list of row dicts.

    Columns (tab-delimited):
        County, Election Date, Precinct, Contest Group ID, Contest Type,
        Contest Name, Choice, Choice Party, Vote For, Election Day,
        Early Voting, Absentee by Mail, Provisional, Total Votes, Real Precinct
    """
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    txt_names = [n for n in z.namelist() if n.endswith(".txt")]
    if not txt_names:
        return []

    rows: list[dict] = []
    with z.open(txt_names[0]) as f:
        lines = f.read().decode("latin-1").splitlines()

    if not lines:
        return []

    headers = [h.strip() for h in lines[0].split("\t")]

    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < len(headers):
            parts += [""] * (len(headers) - len(parts))
        row = {headers[i]: parts[i].strip() for i in range(len(headers))}
        rows.append(row)

    return rows

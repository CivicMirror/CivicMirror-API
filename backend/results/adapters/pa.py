"""
Pennsylvania electionreturns.pa.gov results adapter.

The Report Center export is the preferred source: one CSV contains all counties,
offices, candidates, and vote-mode splits for an election.

The JSON/CSV endpoints do not require a warmed session under normal conditions
(verified 2026-07-22: a plain, cookie-less request succeeds). Imperva only
gates the site occasionally; a Playwright-driven session actually gets *worse*
treatment than a bare request — Imperva's bot fingerprinting flags the
headless-browser session and 403s API calls made with its cookies, even though
an unauthenticated request to the same endpoint succeeds. So the client no
longer warms a session up front: it tries the plain request first and only
falls back to a Playwright-warmed session (once, cached for the client's
lifetime) if that plain request comes back 403.

The JSON endpoints also return their payload as a JSON-encoded *string*
(ASP.NET Web API action returning `string`, not the object itself) — e.g.
`"{\"Table\":[...]}"` rather than `{"Table": [...]}` — so responses need a
second `json.loads()` after `resp.json()`.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import logging
from collections import OrderedDict
from typing import Any

import requests
from django.core.cache import cache
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from integrations.pa_sos.mappers import normalize_contest_name

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.electionreturns.pa.gov"
_TIMEOUT = 60
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
_TYPE_BY_ELECTION_TYPE = {
    "primary": "P",
    "general": "G",
    "special": "S",
}


class PaElectionReturnsClient:
    def __init__(self, base_url: str = _BASE_URL, timeout: int = _TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)
        self._playwright_ctx = None
        self._playwright = None
        self._browser = None
        self._session_warmed = False

    def __enter__(self):
        return self

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

    def warm_session(self) -> None:
        self._playwright_ctx = Stealth().use_sync(sync_playwright())
        self._playwright = self._playwright_ctx.__enter__()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
        )
        context = self._browser.new_context(user_agent=_HEADERS["User-Agent"])
        page = context.new_page()
        page.goto(f"{self.base_url}/ReportCenter/Reports", timeout=self.timeout * 1000)
        page.wait_for_load_state("networkidle", timeout=self.timeout * 1000)

        for cookie in context.cookies():
            self.session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )
        self._session_warmed = True

    def _request_with_warm_retry(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """
        Try a plain (unwarmed) request first. Only pay for a Playwright session
        — and only once per client lifetime — if the plain request is actually
        blocked (403). Warming unconditionally is counterproductive: Imperva's
        bot fingerprinting flags the headless-browser session itself, so a
        Playwright-warmed session can get 403'd where a bare request succeeds.
        """
        url = f"{self.base_url}{path}"
        resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        if resp.status_code == 403 and not self._session_warmed:
            logger.warning("pa_electionreturns.client.403_retry_with_warm_session path=%s", path)
            self.warm_session()
            resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp

    @staticmethod
    def _decode_json(resp: requests.Response) -> Any:
        """
        electionreturns.pa.gov's ASP.NET Web API actions return `string`, so
        the JSON body is itself a JSON-encoded string (e.g. '"{\\"Table\\":[]}"')
        rather than the object directly — needs a second decode.
        """
        data = resp.json()
        if isinstance(data, str):
            data = json.loads(data)
        return data

    def get_election_list(self) -> list[dict[str, Any]]:
        resp = self._request_with_warm_retry("GET", "/api/Reports/GetElectionList")
        data = self._decode_json(resp)
        if isinstance(data, dict):
            return data.get("Table") or []
        return data if isinstance(data, list) else []

    def get_filter_data(self, election_id: int, election_subtype: str) -> dict[str, Any]:
        resp = self._request_with_warm_retry(
            "GET",
            "/api/Reports/GetFilterData",
            params={"electionId": election_id, "electionsubtype": election_subtype},
        )
        data = self._decode_json(resp)
        return data if isinstance(data, dict) else {}

    def generate_report(self, payload: dict[str, Any]) -> str:
        resp = self._request_with_warm_retry(
            "POST",
            "/api/Reports/GenerateReport",
            json=payload,
            headers={"Content-Type": "application/json", **_HEADERS},
        )
        return resp.text


def _safe_int(value: Any) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip())
    except (TypeError, ValueError):
        return 0


def _unique_ints(values: list[Any]) -> list[int]:
    seen: OrderedDict[int, None] = OrderedDict()
    for value in values:
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            continue
        seen.setdefault(int_value, None)
    return list(seen)


def _build_report_payload(election_id: int, election_subtype: str, filter_data: dict[str, Any]) -> dict[str, Any]:
    candidates = filter_data.get("Table2") or []
    return {
        "ElectionID": election_id,
        "ElectionsubType": election_subtype,
        "OfficeIds": _unique_ints([row.get("OfficeID") for row in filter_data.get("Table") or []]),
        "PartyIds": _unique_ints([row.get("PartyID") for row in filter_data.get("Table1") or []]),
        "DistrictIds": _unique_ints([row.get("DistrictID") for row in candidates]),
        "CandidateIds": _unique_ints([row.get("CandidateID") for row in candidates]),
        "CountyIds": [],
        "RetOfficeIds": [],
        "ReferendumIds": [],
        "ReferendumDetailIds": [],
        "ReportType": "D",
        "ExportType": "C",
        "FileName": "Official",
    }


def _parse_report_csv(csv_text: str, result_type: str = "official") -> list[ResultRow]:
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    rows: list[ResultRow] = []
    aggregates: OrderedDict[tuple[str, str, str], ResultRow] = OrderedDict()

    for record in reader:
        office = (record.get("Office Name") or "").strip()
        district = (record.get("District Name") or "").strip()
        candidate_name = (record.get("Candidate Name") or "").strip()
        county = (record.get("County Name") or "").strip()
        office_title = normalize_contest_name(office, district)

        raw_base = {
            "election_name": (record.get("Election Name") or "").strip(),
            "county": county,
            "office_raw": office,
            "district_raw": district,
            "party": (record.get("Party Name") or "").strip(),
        }

        yes_votes = _safe_int(record.get("Yes Votes"))
        no_votes = _safe_int(record.get("No Votes"))
        if yes_votes or no_votes:
            _append_option_row(rows, aggregates, record, office_title, "Yes", yes_votes, result_type, raw_base)
            _append_option_row(rows, aggregates, record, office_title, "No", no_votes, result_type, raw_base)
            continue

        vote_count = _safe_int(record.get("Votes"))
        raw = {
            **raw_base,
            "election_day_votes": _safe_int(record.get("Election Day Votes")),
            "mail_votes": _safe_int(record.get("Mail Votes")),
            "provisional_votes": _safe_int(record.get("Provisional Votes")),
        }
        row = ResultRow(
            candidate_name=candidate_name or None,
            option_label=None,
            vote_count=vote_count,
            vote_pct=None,
            is_winner=None,
            result_type=result_type,
            office_title=office_title,
            jurisdiction_fragment=county,
            raw=raw,
        )
        rows.append(row)
        _add_aggregate(aggregates, row)

    rows.extend(aggregates.values())
    return rows


def _append_option_row(
    rows: list[ResultRow],
    aggregates: OrderedDict[tuple[str, str, str], ResultRow],
    record: dict[str, str],
    office_title: str,
    option_label: str,
    vote_count: int,
    result_type: str,
    raw_base: dict[str, Any],
) -> None:
    if option_label == "Yes":
        election_day = _safe_int(record.get("ElectionDay Yes Votes"))
        mail = _safe_int(record.get("Mail Yes Votes"))
        provisional = _safe_int(record.get("Provisional Yes Votes"))
    else:
        election_day = _safe_int(record.get("Election Day No Votes"))
        mail = _safe_int(record.get("Mail No Votes"))
        provisional = _safe_int(record.get("Provisional No Votes"))

    row = ResultRow(
        candidate_name=None,
        option_label=option_label,
        vote_count=vote_count,
        vote_pct=None,
        is_winner=None,
        result_type=result_type,
        office_title=office_title,
        jurisdiction_fragment=raw_base["county"],
        raw={
            **raw_base,
            "election_day_votes": election_day,
            "mail_votes": mail,
            "provisional_votes": provisional,
        },
    )
    rows.append(row)
    _add_aggregate(aggregates, row)


def _add_aggregate(aggregates: OrderedDict[tuple[str, str, str], ResultRow], row: ResultRow) -> None:
    label = row.candidate_name or row.option_label or ""
    kind = "candidate" if row.candidate_name else "option"
    key = (row.office_title or "", kind, label)
    existing = aggregates.get(key)

    if existing is None:
        aggregates[key] = ResultRow(
            candidate_name=row.candidate_name,
            option_label=row.option_label,
            vote_count=row.vote_count,
            vote_pct=None,
            is_winner=None,
            result_type=row.result_type,
            office_title=row.office_title,
            jurisdiction_fragment="",
            raw={
                "pa_aggregate": "statewide",
                "election_day_votes": row.raw.get("election_day_votes", 0),
                "mail_votes": row.raw.get("mail_votes", 0),
                "provisional_votes": row.raw.get("provisional_votes", 0),
            },
        )
        return

    existing.vote_count += row.vote_count
    existing.raw["election_day_votes"] += row.raw.get("election_day_votes", 0)
    existing.raw["mail_votes"] += row.raw.get("mail_votes", 0)
    existing.raw["provisional_votes"] += row.raw.get("provisional_votes", 0)


def _cache_key(election_id: int) -> str:
    return f"pa_electionreturns:report_hash:{election_id}"


def _metadata_int(meta: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = meta.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _metadata_str(meta: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = (meta.get(key) or "").strip() if isinstance(meta.get(key), str) else meta.get(key)
        if value:
            return str(value)
    return ""


def _parse_registry_date(value: Any) -> datetime.date | None:
    if isinstance(value, datetime.date):
        return value
    text = str(value or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _resolve_from_registry(election, registry: list[dict[str, Any]]) -> dict[str, Any] | None:
    target_type = _TYPE_BY_ELECTION_TYPE.get((getattr(election, "election_type", "") or "").lower())
    for item in registry:
        item_date = _parse_registry_date(item.get("ElectionDate") or item.get("Electiondate"))
        item_type = item.get("ElectionType") or item.get("Electiontype")
        if item_date != election.election_date:
            continue
        if target_type and item_type != target_type:
            continue
        return item
    return None


def _result_type_from_status(status: str) -> str:
    normalized = (status or "").strip().lower()
    return "official" if normalized in {"o", "official"} else "unofficial"


@register
class PennsylvaniaAdapter(StateResultsAdapter):
    state = "PA"
    VERSION_CACHE_TIMEOUT = 86400 * 30

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return _cache_key(election_id)

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("pa_results.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        meta = election.source_metadata or {}
        pa_election_id = _metadata_int(meta, "pa_election_id", "pa_electionreturns_id")
        election_subtype = _metadata_str(meta, "pa_election_subtype", "pa_election_type")
        pa_status = _metadata_str(meta, "pa_election_status", "pa_result_type")

        source_url = f"{_BASE_URL}/ReportCenter/Reports"
        try:
            with PaElectionReturnsClient() as client:
                if not pa_election_id or not election_subtype:
                    registry = client.get_election_list()
                    resolved = _resolve_from_registry(election, registry)
                    if not resolved:
                        return AdapterResult(
                            rows=[],
                            source_url=source_url,
                            mapping_confidence="none",
                            notes="No PA electionreturns registry match for election date/type",
                        )
                    pa_election_id = _metadata_int(resolved, "Electionid", "ElectionID")
                    election_subtype = _metadata_str(resolved, "ElectionType", "Electiontype")
                    pa_status = _metadata_str(resolved, "ElectionStatus", "Electionstatus") or pa_status

                filter_data = client.get_filter_data(pa_election_id, election_subtype)
                payload = _build_report_payload(pa_election_id, election_subtype, filter_data)
                csv_text = client.generate_report(payload)
        except Exception as exc:
            logger.error("pa_results.adapter.fetch_failed election=%d: %s", election_id, exc)
            raise

        report_hash = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
        if cache.get(self.version_cache_key(election_id)) == report_hash:
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=report_hash,
            )

        result_type = (
            meta.get("pa_result_type")
            if meta.get("pa_result_type") in {"official", "unofficial"}
            else _result_type_from_status(pa_status or "official")
        )
        rows = _parse_report_csv(csv_text, result_type=result_type)
        logger.info("pa_results.adapter.fetched election=%d rows=%d hash=%s", election_id, len(rows), report_hash)

        return AdapterResult(
            rows=rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=report_hash,
        )

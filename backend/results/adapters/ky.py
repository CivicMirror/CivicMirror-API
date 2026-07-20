"""
Kentucky (KY) results adapter — Kentucky SBE documented XML downloads.

Source: https://vrsws.sos.ky.gov/liveresults/Data

The rendered /liveresults HTML site is browser-facing and may be protected by
Kentucky/Akamai policy controls. This adapter uses only the documented XML
download paths and treats an Acceptable Use Policy HTML response as an
unavailable feed.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
from xml.etree import ElementTree as ET

import requests
from django.core.cache import cache

from results.models import OfficialResult

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_DATA_BASE = "https://vrsws.sos.ky.gov/liveresults/Data"
_TIMEOUT = 60
_CACHE_TTL = 86400 * 30
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

_HEADERS = {
    "User-Agent": "CivicMirror/1.0 (+https://civicmirror.app; contact: support@civicmirror.app)",
    "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
}

_MEASURE_KEYWORDS = frozenset({
    "amendment", "measure", "proposition", "question", "referendum",
    "initiative", "bond", "levy", "ordinance",
})


class KentuckyPolicyBlockError(Exception):
    """Kentucky returned its Acceptable Use Policy/bot-warning page."""


class KentuckyXmlClient:
    def __init__(self, timeout: int = _TIMEOUT):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def _fetch(self, dataset: str) -> bytes:
        url = f"{_DATA_BASE}/{dataset}"
        try:
            resp = self._session.get(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise RuntimeError(f"KY XML GET failed: {exc}") from exc

        if resp.status_code in _RETRYABLE_STATUSES:
            raise RuntimeError(f"KY XML returned {resp.status_code} for {url}")
        content = resp.content
        if _looks_like_policy_block(content):
            raise KentuckyPolicyBlockError("Kentucky SBE Acceptable Use Policy response")
        resp.raise_for_status()
        return content

    def fetch_elections(self) -> bytes:
        return self._fetch("Elections")

    def fetch_contests(self) -> bytes:
        return self._fetch("Contests")

    def fetch_candidates(self) -> bytes:
        return self._fetch("Candidates")

    def fetch_current_results(self, *, include_local: bool = False) -> bytes:
        dataset = "CurrentResults" if include_local else "CurrentResultsExcludeLocal"
        return self._fetch(dataset)


def _looks_like_policy_block(content: bytes) -> bool:
    lowered = content[:4096].lower()
    return b"acceptable use policy" in lowered or b"<html" in lowered


def source_version_for(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _elements(root: ET.Element, name: str) -> list[ET.Element]:
    normalized = name.lower()
    return [el for el in root.iter() if _local_name(el.tag).lower() == normalized]


def _attr(el: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for key, value in el.attrib.items():
        if key.lower() in wanted:
            return (value or "").strip()
    return ""


def _safe_int(value: str | int | None) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip())
    except ValueError:
        return 0


def _safe_date(value: str) -> datetime.date | None:
    value = (value or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _bool_attr(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_xml(xml_bytes: bytes) -> ET.Element:
    return ET.fromstring(xml_bytes)


def _parse_elections(elections_xml: bytes) -> list[dict[str, str]]:
    root = _parse_xml(elections_xml)
    elections = []
    for el in _elements(root, "Election"):
        elections.append({
            "election_id": _attr(el, "ElectionId", "election_id"),
            "name": _attr(el, "ElectionName", "election_name"),
            "type": _attr(el, "ElectionType", "election_type"),
            "date": _attr(el, "ElectionDate", "election_date"),
        })
    return elections


def select_ky_election_id(election, elections_xml: bytes) -> str:
    meta = election.source_metadata or {}
    configured = str(meta.get("ky_election_id") or "").strip()
    if configured:
        return configured

    target_date = election.election_date
    target_type = (election.election_type or "").replace("_", " ").lower()
    same_date = [
        candidate for candidate in _parse_elections(elections_xml)
        if _safe_date(candidate["date"]) == target_date
    ]

    # Prefer an exact type match first: substring containment alone would let
    # target_type="primary" match a same-day "Primary Runoff" candidate.
    for candidate in same_date:
        if candidate["type"].replace("_", " ").lower() == target_type:
            return candidate["election_id"]

    for candidate in same_date:
        if target_type in candidate["type"].replace("_", " ").lower():
            return candidate["election_id"]

    return ""


def _parse_contests(contests_xml: bytes, election_id: str) -> dict[str, dict[str, str]]:
    root = _parse_xml(contests_xml)
    contests = {}
    for el in _elements(root, "Contest"):
        if _attr(el, "ElectionId", "election_id") != election_id:
            continue
        contest_id = _attr(el, "ContestId", "contest_id")
        if not contest_id:
            continue
        contests[contest_id] = {
            "contest_id": contest_id,
            "name": _attr(el, "ContestName", "contest_name"),
            "scope_unit_id": _attr(el, "ContestScopeUnitId", "contest_scope_unit_id"),
            "is_partisan": _attr(el, "IsPartisan", "is_partisan"),
            "is_uncontested": _attr(el, "IsUncontested", "is_uncontested"),
            "selectable_option": _attr(el, "SelectableOption", "selectable_option"),
            "party_id": _attr(el, "PoliticalPartyId", "political_party_id"),
        }
    return contests


def _parse_candidates(candidates_xml: bytes, election_id: str) -> dict[tuple[str, str], dict[str, str]]:
    root = _parse_xml(candidates_xml)
    candidates = {}
    for el in _elements(root, "Candidate"):
        if _attr(el, "ElectionId", "election_id") != election_id:
            continue
        contest_id = _attr(el, "ContestId", "contest_id")
        candidate_id = _attr(el, "CandidateId", "candidate_id")
        if not contest_id or not candidate_id:
            continue
        candidates[(contest_id, candidate_id)] = {
            "contest_id": contest_id,
            "candidate_id": candidate_id,
            "ballot_name": _attr(el, "BallotName", "ballot_name"),
            "party_id": _attr(el, "PoliticalPartyId", "political_party_id"),
            "is_incumbent": _attr(el, "IsIncumbent", "is_incumbent"),
            "is_write_in": _attr(el, "IsWriteIn", "is_write_in"),
            "is_withdrawn": _attr(el, "IsWithdrawn", "is_withdrawn"),
        }
    return candidates


def _parse_report_data(current_results_xml: bytes) -> dict[str, dict[str, str]]:
    root = _parse_xml(current_results_xml)
    reports = {}
    for el in _elements(root, "ReportData"):
        gpu_id = _attr(el, "gpu_id", "Gpu_id", "Gup_id")
        if not gpu_id:
            continue
        reports[gpu_id] = {
            "status": _attr(el, "status", "Status"),
            "precinct_participating": _attr(el, "precinct_participating", "Precinct_participating"),
            "precinct_reporting": _attr(el, "precinct_reporting", "Precinct_reporting"),
            "ballots_cast": _attr(el, "ballots_cast", "Ballots_cast"),
            "registered_voters": _attr(el, "registered_voters", "Registered_voters"),
        }
    return reports


def _is_measure_contest(contest: dict[str, str]) -> bool:
    name = (contest.get("name") or "").lower()
    return any(keyword in name for keyword in _MEASURE_KEYWORDS)


def parse_ky_xml_results(
    election_id: str,
    contests_xml: bytes,
    candidates_xml: bytes,
    current_results_xml: bytes,
) -> list[ResultRow]:
    contests = _parse_contests(contests_xml, election_id)
    candidates = _parse_candidates(candidates_xml, election_id)
    report_data = _parse_report_data(current_results_xml)
    root = _parse_xml(current_results_xml)

    rows: list[ResultRow] = []
    for el in _elements(root, "CandidateData"):
        contest_id = _attr(el, "contest_id", "Contest_id")
        candidate_id = _attr(el, "candidate_id", "Candidate_id")
        gpu_id = _attr(el, "gpu_id", "Gpu_id", "Gup_id")
        contest = contests.get(contest_id)
        candidate = candidates.get((contest_id, candidate_id))
        if not contest or not candidate:
            continue

        total_votes = _safe_int(_attr(el, "total_votes", "Total_votes"))
        election_day_votes = _safe_int(_attr(el, "election_day_votes", "Election_day_votes"))
        report = report_data.get(gpu_id, {})
        is_write_in = _bool_attr(candidate["is_write_in"]) or candidate["ballot_name"].strip().lower() == "write-in"
        is_measure = _is_measure_contest(contest)

        rows.append(ResultRow(
            office_title=contest["name"],
            candidate_name=None if is_write_in or is_measure else candidate["ballot_name"],
            option_label=candidate["ballot_name"] if is_measure else None,
            vote_count=total_votes,
            vote_pct=None,
            is_winner=None,
            result_type=OfficialResult.ResultType.UNOFFICIAL,
            is_write_in_aggregate=is_write_in and not is_measure,
            jurisdiction_fragment=gpu_id,
            raw={
                "source": "ky_sbe_live_xml",
                "election_id": election_id,
                "contest_code": contest_id,
                "contest_id": contest_id,
                "candidate_id": candidate_id,
                "gpu_id": gpu_id,
                "election_day_votes": election_day_votes,
                "absentee_votes": total_votes - election_day_votes,
                "reporting_status": report.get("status", ""),
                "precinct_participating": _safe_int(report.get("precinct_participating")),
                "precinct_reporting": _safe_int(report.get("precinct_reporting")),
                "ballots_cast": _safe_int(report.get("ballots_cast")),
                "registered_voters": _safe_int(report.get("registered_voters")),
                "is_withdrawn": _bool_attr(candidate["is_withdrawn"]),
                "is_incumbent": _bool_attr(candidate["is_incumbent"]),
                "contest_scope_unit_id": contest.get("scope_unit_id", ""),
                "selectable_option": _safe_int(contest.get("selectable_option")),
            },
        ))

    return rows


@register
class KentuckyAdapter(StateResultsAdapter):
    state = "KY"
    VERSION_CACHE_TIMEOUT = _CACHE_TTL

    def version_cache_key(self, election_id: int) -> str:
        return f"ky_sbe_live_xml:sha256:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("ky_sbe.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        meta = election.source_metadata or {}
        include_local = str(meta.get("ky_results_feed") or "").strip().lower() == "all"
        source_url = f"{_DATA_BASE}/{'CurrentResults' if include_local else 'CurrentResultsExcludeLocal'}"
        client = KentuckyXmlClient()

        try:
            elections_xml = client.fetch_elections()
            ky_election_id = select_ky_election_id(election, elections_xml)
            if not ky_election_id:
                return AdapterResult(
                    rows=[],
                    source_url=source_url,
                    mapping_confidence="none",
                    notes="No matching Kentucky ElectionId found in Elections XML",
                )

            current_results_xml = client.fetch_current_results(include_local=include_local)
            source_version = source_version_for(current_results_xml)
            if cache.get(self.version_cache_key(election_id)) == source_version:
                return AdapterResult(
                    rows=[],
                    source_url=source_url,
                    mapping_confidence="full",
                    unchanged=True,
                    source_version=source_version,
                )

            contests_xml = client.fetch_contests()
            candidates_xml = client.fetch_candidates()
        except KentuckyPolicyBlockError as exc:
            logger.warning("ky_sbe.adapter.policy_block election=%d: %s", election_id, exc)
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="none",
                notes=f"Kentucky XML feed unavailable due to policy block: {exc}",
            )

        rows = parse_ky_xml_results(
            ky_election_id,
            contests_xml=contests_xml,
            candidates_xml=candidates_xml,
            current_results_xml=current_results_xml,
        )
        return AdapterResult(
            rows=rows,
            source_url=source_url,
            mapping_confidence="full" if rows else "none",
            source_version=source_version,
        )

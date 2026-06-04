"""
Arizona (AZ) results adapter — AZ Secretary of State HTTPS XML feed.

Source: https://apps.azsos.gov/ftp/ElectionResults/{year}/State/{election_name}/Results.Summary.xml
Access: HTTPS via requests (confirmed HTTP 200).
Schema: Results.Summary.xml — statewide candidate + ballot question totals.
        totalVotes on each <choice> is the statewide aggregate.

Required Election.source_metadata key (optional — auto-derived if absent):
    az_election_name  str  URL path segment, e.g. "2026 Primary Election"

Auto-derivation maps election_type:
    primary                → "Primary Election"
    general                → "General Election"
    presidential_preference → "Presidential Preference Election"
    <other>                → "{type.title()} Election"

Version caching:
    Cache key: az_sos:ver:{election_pk}
    Value:     fileId string from <electionInformation> (increments each publish)
    TTL:       30 days (written by ingest task after successful DB work)

Race name normalization:
    contestLongName values from the XML differ from CandidateList race names
    used by Stage 1 (integrations/az_sos). Both encode party in the name and
    use different abbreviations for US House races. normalize_contest_name()
    from integrations.az_sos.mappers is applied to every contestLongName so
    that ResultRow.office_title matches Race.office_title exactly, which is
    required for _process_race_results string-equality join to succeed.

Data notes:
    - No winner field in XML; is_winner is always None.
    - No official/unofficial flag; result_type is always 'unofficial'.
    - isWriteIn="true" on a <choice> → is_write_in_aggregate=True.
    - Ballot question choices have no key attribute; raw["choiceKey"] is "".
"""
from __future__ import annotations

import logging
import urllib.parse
from xml.etree import ElementTree as ET

import requests
from django.core.cache import cache

from integrations.az_sos.mappers import normalize_candidate_name, normalize_contest_name
from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_HTTPS_BASE = "https://apps.azsos.gov/ftp/ElectionResults"
_TIMEOUT = 60

_ELECTION_TYPE_TO_LABEL: dict[str, str] = {
    "primary": "Primary Election",
    "general": "General Election",
    "presidential_preference": "Presidential Preference Election",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_int(val, default: int = 0) -> int:
    try:
        return int(str(val).replace(',', '').strip())
    except (ValueError, TypeError):
        return default


def _derive_election_name(election) -> str:
    year = election.election_date.year
    etype = (getattr(election, 'election_type', '') or '').lower().strip()
    label = _ELECTION_TYPE_TO_LABEL.get(etype) or f"{etype.replace('_', ' ').title()} Election"
    return f"{year} {label}"


def _build_url(election) -> str:
    meta = election.source_metadata or {}
    election_name = (meta.get('az_election_name') or '').strip() or _derive_election_name(election)
    year = election.election_date.year
    encoded_name = urllib.parse.quote(election_name)
    return f"{_HTTPS_BASE}/{year}/State/{encoded_name}/Results.Summary.xml"


def _fetch_xml(url: str, timeout: int = _TIMEOUT) -> bytes:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def _parse_results(xml_bytes: bytes) -> tuple[str, list[ResultRow]]:
    """
    Parse Results.Summary.xml into (fileId, [ResultRow]).

    office_title on each ResultRow is normalize_contest_name(contestLongName)
    so it matches Race.office_title created by Stage 1 (integrations/az_sos).
    Returns ("", []) on empty or malformed input.
    """
    root = ET.fromstring(xml_bytes)

    info = root.find('electionInformation')
    file_id = (info.findtext('fileId') or '') if info is not None else ''

    rows: list[ResultRow] = []
    contests_el = root.find('contests')
    if contests_el is None:
        return file_id, rows

    for contest in contests_el.findall('contest'):
        is_question = contest.attrib.get('isQuestion', 'false').lower() == 'true'
        raw_name = (contest.attrib.get('contestLongName') or '').strip()
        # Normalize so office_title matches Race records created by Stage 1.
        office = normalize_contest_name(raw_name) if raw_name else None
        contest_key = contest.attrib.get('key', '')

        # Use direct path choices/choice — not .//choice — to avoid any
        # unintentional descent into nested jurisdiction blocks.
        for choice in contest.findall('choices/choice'):
            raw_choice_name = (choice.attrib.get('choiceName') or '').strip()
            if not raw_choice_name:
                continue
            total = _safe_int(choice.attrib.get('totalVotes', 0))
            xml_is_write_in = choice.attrib.get('isWriteIn', 'false').lower() == 'true'
            choice_key = choice.attrib.get('key', '')

            if is_question:
                candidate_name = None
                option_label = raw_choice_name
                is_write_in_aggregate = False
            else:
                # XML names are "Last, First"; normalize to "First Last" to match
                # Candidate.name stored by Stage 1. Generic "Write-In" aggregate
                # returns candidate_name=None so it attaches at the race level.
                candidate_name, is_write_in_aggregate = normalize_candidate_name(raw_choice_name)
                option_label = None

            rows.append(ResultRow(
                office_title=office,
                candidate_name=candidate_name,
                option_label=option_label,
                vote_count=total,
                vote_pct=None,
                is_winner=None,
                result_type='unofficial',
                is_write_in_aggregate=is_write_in_aggregate or xml_is_write_in,
                raw={'contestKey': contest_key, 'choiceKey': choice_key},
            ))

    return file_id, rows


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

@register
class ArizonaAdapter(StateResultsAdapter):
    state = "AZ"
    VERSION_CACHE_TIMEOUT = 86400 * 30  # 30 days

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return f"az_sos:ver:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        from elections.models import Election

        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("az_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url='', mapping_confidence='none',
                notes=f'Election pk={election_id} not found',
            )

        url = _build_url(election)

        try:
            xml_bytes = _fetch_xml(url)
        except Exception as exc:
            logger.error("az_sos.adapter.fetch_failed url=%s: %s", url, exc)
            raise

        file_id, rows = _parse_results(xml_bytes)

        if not file_id:
            logger.warning("az_sos.adapter.no_file_id url=%s", url)

        cache_key = self.version_cache_key(election_id)
        if file_id and cache.get(cache_key) == file_id:
            logger.debug("az_sos.adapter.unchanged election=%d file_id=%s", election_id, file_id)
            return AdapterResult(
                rows=[], source_url=url, mapping_confidence='full',
                unchanged=True, source_version=file_id,
            )

        logger.info(
            "az_sos.adapter.fetched election=%d rows=%d file_id=%s",
            election_id, len(rows), file_id,
        )

        return AdapterResult(
            rows=rows,
            source_url=url,
            mapping_confidence='full',
            source_version=file_id,
        )

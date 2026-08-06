"""Hawaii results adapter.

Hawaii publishes structured official result text files under the Office of
Elections results index:
    https://elections.hawaii.gov/election-results/

For regular elections from 2004 forward the preferred source is the UTF-16
statewide summary text file, with a matching precinct-detail text file for
precinct-level drill-down. The adapter discovers those files from the
results index, decodes them as CSV, and normalizes each row into ResultRow
objects that match the Stage 1 contest_variant identity used by the Hawaii
candidate ingest.

Two file shapes exist and both must be handled (see _resolve_party_code):
primary files populate the Contest Party column and leave candidate names
bare; general files leave that column empty and prefix the party onto the
candidate name.

Known identity gaps, measured against the real 2024 primary (121 of 145
contest_variants match the candidate report):

* County contests lose their jurisdiction. The candidate report says
  "HAWAII COUNCILMEMBER, DIST 1" while the result files say
  "Councilmember, Dist 1"; the county appears in no result column. It is
  only inferable from media.txt precinct prefixes, which are state house
  districts and therefore reapportionment-vintage dependent, so it is not
  inferred here. This accounts for 22 of the 24 unmatched variants.
* Write-in aggregate rows have no filed candidate and so no Stage 1 race.
  That accounts for the other 2.
* In general-election files, nonpartisan county/OHA contests carry no party
  in either location, so they cannot be distinguished from statewide
  nonpartisan contests by party alone.

The durable fix is the one the state research recommends: join on Hawaii's
own election-scoped contest_id (kept in raw["contest_id"]) by attaching it
to the Race once results publish, rather than string-matching titles. That
requires a linking step in Stage 1 and is not done here.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import logging
import re
from collections import defaultdict

import requests
from django.core.cache import cache

from elections.models import Election
from results.models import OfficialResult

from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_INDEX_URL = "https://elections.hawaii.gov/election-results/"
_RESULT_URL_RE = re.compile(r'href=["\']([^"\']+(?:summary|media)\.txt)["\']', re.IGNORECASE)
_PARTY_PREFIX_TO_NAME = {
    "D": "DEMOCRATIC",
    "R": "REPUBLICAN",
    "G": "GREEN",
    "L": "LIBERTARIAN",
    "N": "NONPARTISAN",
    # County/OHA contests carry "NON" in the primary files; the candidate
    # report labels the same contests "NONPARTISAN SPECIAL".
    "NON": "NONPARTISAN SPECIAL",
    "W": "WRITE-IN",
}


def _normalize_whitespace(value: str) -> str:
    return " ".join((value or "").replace("\r", "\n").split())


def _decode_result_text(file_bytes: bytes) -> str:
    """Decode a Hawaii result file, choosing the encoding from its BOM.

    The current files are UTF-16 with a BOM, but the pre-election placeholder
    the index links before results publish is plain ASCII ("Information will be
    posted at a later date."). Hardcoding utf-16 turned that into a decode
    error that surfaced as a misleading "fetch failed".
    """
    if file_bytes.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return file_bytes.decode("utf-16")
    if file_bytes.startswith(codecs.BOM_UTF8):
        return file_bytes.decode("utf-8-sig")
    for encoding in ("utf-16", "utf-8", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def _looks_like_result_file(text: str) -> bool:
    """True when the payload is an actual result export rather than a stub."""
    return "Format#1" in text or any(
        line.startswith("#Contest") or line.startswith('#"Precinct')
        for line in text.splitlines()[:5]
    )


def _parse_candidate_name(raw_name: str) -> tuple[str, str]:
    name = (raw_name or "").replace("\r", "\n").strip()
    if not name:
        return "", ""

    party_code = ""
    first_line = name.splitlines()[0].strip()
    match = re.match(r"^\((?P<party>[A-Z]+)\)\s*(?P<body>.*)$", first_line)
    if match:
        party_code = match.group("party").strip()
        first_line = match.group("body").strip()

    return _normalize_whitespace(first_line), party_code


def _party_name_from_code(code: str) -> str:
    cleaned = (code or "").strip().upper()
    return _PARTY_PREFIX_TO_NAME.get(cleaned, cleaned)


def _contest_variant(contest_title: str, party_name: str) -> str:
    contest = _normalize_whitespace(contest_title).lower()
    party = _normalize_whitespace(party_name).lower()
    return f"hi:{contest}:{party}"


def _source_identity(contest_title: str, party_name: str) -> str:
    return _contest_variant(contest_title, party_name)


def _resolve_party_code(contest_party: str, name_party_code: str, choice_party: str = "") -> str:
    """Pick the party code from wherever this file era keeps it.

    Hawaii publishes two shapes. Primary files populate the Contest Party
    column and leave candidate names bare ("POHLMAN, Emma Jane Avila").
    General files leave Contest Party empty and prefix the party onto the
    candidate name ("(D) HARRIS, Kamala D."). Reading only the name prefix
    left every primary row with an empty party.
    """
    for value in (contest_party, name_party_code, choice_party):
        cleaned = (value or "").strip().upper()
        if cleaned:
            return cleaned
    return ""


def _row_base_raw(
    *,
    contest_id: str,
    contest_title: str,
    contest_type: str,
    contest_party: str,
    candidate_id: str,
    candidate_seq_nbr: str,
    candidate_party: str,
    party_code: str,
    file_kind: str,
    file_url: str,
) -> dict[str, str]:
    resolved_code = _resolve_party_code(contest_party, party_code, candidate_party)
    party_name = _party_name_from_code(resolved_code)
    raw = {
        "contest_id": contest_id,
        "contest_title": contest_title,
        "contest_type": contest_type,
        "contest_party": contest_party,
        "candidate_id": candidate_id,
        "candidate_seq_nbr": candidate_seq_nbr,
        "candidate_party": candidate_party,
        "party_code": resolved_code,
        "party_name": party_name,
        "contest_variant": _source_identity(contest_title, party_name),
        "file_kind": file_kind,
        "file_url": file_url,
    }
    return raw


def _mark_summary_winners(rows: list[ResultRow]) -> None:
    # Group by Hawaii's contest id, not by contest_variant. The variant carries
    # the party, so in a general election every candidate lands in a group of
    # one and all of them get flagged winner - on the real 2024 general file
    # that marked all six presidential candidates, including ones who lost.
    # Each (contest, party) pair already has its own contest id in the primary
    # files, so the id is the correct grouping for both eras.
    groups: dict[str, list[ResultRow]] = defaultdict(list)
    for row in rows:
        groups[(row.raw.get("contest_id") or "").strip()].append(row)

    for group_rows in groups.values():
        if not group_rows:
            continue
        top_vote = max(row.vote_count for row in group_rows)
        if top_vote <= 0:
            for row in group_rows:
                row.is_winner = False
            continue
        for row in group_rows:
            row.is_winner = row.vote_count == top_vote


def _parse_summary_text(file_bytes: bytes, source_url: str) -> list[ResultRow]:
    text = _decode_result_text(file_bytes)
    reader = csv.reader(io.StringIO(text))

    rows: list[ResultRow] = []
    for record in reader:
        if not record or record[0] == "Format#1" or record[0].startswith("#"):
            continue
        if len(record) < 21:
            continue

        contest_id = record[0].strip()
        contest_title = record[1].strip()
        contest_type = record[3].strip()
        contest_party = record[4].strip()
        candidate_id = record[14].strip()
        candidate_raw = record[15]
        candidate_seq_nbr = record[16].strip()
        candidate_party = record[17].strip()
        mail_votes = int(record[18] or 0)
        in_person_votes = int(record[19] or 0)
        total_votes = int(record[20] or 0)

        candidate_name, party_code = _parse_candidate_name(candidate_raw)
        raw = _row_base_raw(
            contest_id=contest_id,
            contest_title=contest_title,
            contest_type=contest_type,
            contest_party=contest_party,
            candidate_id=candidate_id,
            candidate_seq_nbr=candidate_seq_nbr,
            candidate_party=candidate_party,
            party_code=party_code,
            file_kind="summary",
            file_url=source_url,
        )
        rows.append(ResultRow(
            candidate_name=candidate_name or None,
            option_label=None,
            vote_count=total_votes,
            vote_pct=None,
            is_winner=None,
            result_type=OfficialResult.ResultType.OFFICIAL,
            office_title=contest_title,
            raw={
                **raw,
                "candidate_name_raw": candidate_raw.strip(),
                "mail_votes": mail_votes,
                "in_person_votes": in_person_votes,
                "total_votes": total_votes,
            },
        ))

    _mark_summary_winners(rows)
    return rows


def _parse_media_text(file_bytes: bytes, source_url: str) -> list[ResultRow]:
    text = _decode_result_text(file_bytes)
    reader = csv.reader(io.StringIO(text))

    rows: list[ResultRow] = []
    for record in reader:
        if not record or record[0] == "Format#1" or record[0].startswith("#"):
            continue
        if len(record) < 15:
            continue

        precinct_name = record[0].strip()
        split_name = record[1].strip()
        precinct_split_id = record[2].strip()
        contest_id = record[6].strip()
        contest_title = record[7].strip()
        contest_party = record[8].strip()
        choice_id = record[9].strip()
        candidate_raw = record[10]
        choice_party = record[11].strip()
        candidate_type = record[12].strip()
        mail_votes = int(record[13] or 0)
        in_person_votes = int(record[14] or 0)
        total_votes = mail_votes + in_person_votes

        candidate_name, party_code = _parse_candidate_name(candidate_raw)
        rows.append(ResultRow(
            candidate_name=candidate_name or None,
            option_label=None,
            vote_count=total_votes,
            vote_pct=None,
            is_winner=None,
            result_type=OfficialResult.ResultType.OFFICIAL,
            office_title=contest_title,
            jurisdiction_fragment=precinct_split_id or precinct_name,
            raw={
                **_row_base_raw(
                    contest_id=contest_id,
                    contest_title=contest_title,
                    contest_type="MEDIA",
                    contest_party=contest_party,
                    candidate_id=choice_id,
                    candidate_seq_nbr="",
                    candidate_party=choice_party,
                    party_code=party_code,
                    file_kind="media",
                    file_url=source_url,
                ),
                "precinct_name": precinct_name,
                "split_name": split_name,
                "precinct_split_id": precinct_split_id,
                "candidate_name_raw": candidate_raw.strip(),
                "candidate_type": candidate_type,
                "mail_votes": mail_votes,
                "in_person_votes": in_person_votes,
                "total_votes": total_votes,
            },
        ))

    return rows


def _section_name_for_election(election_type: str) -> str:
    election_type = (election_type or "").lower()
    if "primary" in election_type:
        return "primary"
    if "general" in election_type:
        return "general"
    if "special" in election_type:
        return "special"
    return election_type or "general"


def _discover_result_urls(index_html: str, election: Election) -> tuple[str, str]:
    year = election.election_date.year
    section = _section_name_for_election(election.election_type)
    candidates = [href for href in _RESULT_URL_RE.findall(index_html or "")]

    def _pick(filename: str) -> str:
        lowered = filename.lower()
        direct_matches = [
            href for href in candidates
            if f"/{year}/" in href.lower()
            and f"/{section}/" in href.lower()
            and href.lower().endswith(lowered)
        ]
        if direct_matches:
            return direct_matches[0]
        placeholder_matches = [
            href for href in candidates
            if href.lower().endswith(lowered) and "placeholder" in href.lower()
        ]
        if placeholder_matches:
            return placeholder_matches[0]
        # Deliberately no "first file on the page" fallback. The index lists
        # every year from 1992 forward, so returning an arbitrary match would
        # ingest another election's results under this election's id. Failing
        # to discover a URL is reported as "not found" by the caller instead.
        return ""

    return _pick("summary.txt"), _pick("media.txt")


def _fetch_bytes(url: str) -> bytes:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


@register
class HawaiiAdapter(StateResultsAdapter):
    state = "HI"
    VERSION_CACHE_TIMEOUT = 86400 * 30

    @classmethod
    def version_cache_key(cls, election_id: int) -> str:
        return f"hi_olvr:results_version:{election_id}"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("hi_results.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[], source_url="", mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        raw_url = (election.results_url or "").strip()
        index_url = _INDEX_URL
        summary_url = ""
        media_url = ""

        if raw_url.lower().endswith("summary.txt"):
            summary_url = raw_url
            media_url = raw_url.rsplit("/", 1)[0] + "/media.txt"
            index_url = raw_url.rsplit("/", 1)[0] + "/"
        elif raw_url.lower().endswith("media.txt"):
            media_url = raw_url
            summary_url = raw_url.rsplit("/", 1)[0] + "/summary.txt"
            index_url = raw_url.rsplit("/", 1)[0] + "/"
        elif raw_url:
            index_url = raw_url.rstrip("/") + "/"

        if not summary_url:
            index_html = ""
            try:
                index_resp = requests.get(index_url, timeout=60)
                index_resp.raise_for_status()
                index_html = index_resp.text
            except Exception as exc:
                logger.warning(
                    "hi_results.adapter.index_fetch_failed election=%d url=%s err=%s",
                    election_id, index_url, exc,
                )
                return AdapterResult(
                    rows=[], source_url=index_url, mapping_confidence="none",
                    notes=f"Failed to fetch Hawaii results index: {exc}",
                )

            summary_url, media_url = _discover_result_urls(index_html, election)

        if not summary_url:
            logger.warning("hi_results.adapter.no_summary_url election=%d", election_id)
            return AdapterResult(
                rows=[], source_url=index_url, mapping_confidence="none",
                notes="Could not locate Hawaii summary.txt in the results index",
            )

        notes: list[str] = []
        fingerprint_parts: list[str] = []
        rows: list[ResultRow] = []

        try:
            summary_bytes = _fetch_bytes(summary_url)
            fingerprint_parts.append(hashlib.sha256(summary_bytes).hexdigest())
            # Before an election the index links a stub reading "Information
            # will be posted at a later date." Report that as "no results yet"
            # rather than letting it fall through as a parse/fetch failure.
            if not _looks_like_result_file(_decode_result_text(summary_bytes)):
                logger.info(
                    "hi_results.adapter.results_not_published election=%d url=%s",
                    election_id, summary_url,
                )
                return AdapterResult(
                    rows=[], source_url=index_url, mapping_confidence="none",
                    notes="Hawaii results are not published yet (placeholder file)",
                    source_version=fingerprint_parts[0],
                )
            rows.extend(_parse_summary_text(summary_bytes, summary_url))
        except Exception as exc:
            logger.warning(
                "hi_results.adapter.summary_fetch_failed election=%d url=%s err=%s",
                election_id, summary_url, exc,
            )
            return AdapterResult(
                rows=[], source_url=index_url, mapping_confidence="none",
                notes=f"Failed to fetch Hawaii summary results: {exc}",
            )

        if media_url:
            try:
                media_bytes = _fetch_bytes(media_url)
                fingerprint_parts.append(hashlib.sha256(media_bytes).hexdigest())
                rows.extend(_parse_media_text(media_bytes, media_url))
            except Exception as exc:
                logger.warning(
                    "hi_results.adapter.media_fetch_failed election=%d url=%s err=%s",
                    election_id, media_url, exc,
                )
                notes.append(f"media_error:{exc}")

        fingerprint = "|".join(fingerprint_parts)
        cache_key = self.version_cache_key(election_id)
        if fingerprint and cache.get(cache_key) == fingerprint:
            return AdapterResult(
                rows=[],
                source_url=index_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=fingerprint,
            )

        if not rows:
            return AdapterResult(
                rows=[],
                source_url=index_url,
                mapping_confidence="none",
                notes="No Hawaii result rows were parsed",
                source_version=fingerprint,
            )

        mapping_confidence = "partial" if notes else "full"
        return AdapterResult(
            rows=rows,
            source_url=index_url,
            mapping_confidence=mapping_confidence,
            notes="; ".join(notes),
            source_version=fingerprint,
        )

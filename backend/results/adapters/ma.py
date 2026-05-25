"""
Massachusetts results adapter using electionstats.state.ma.us CSV downloads.

All electionstats results are post-certification data — result_type is always "official".

Election electionstats_id is stored in Election.source_metadata["electionstats_id"]
and is populated programmatically by the sync_ma_elections task.

Version cache key: "ma_sos:hash:{election_id}"
Cache value:       SHA-256 hex digest of the CSV body.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
from typing import Optional

import requests
from django.core.cache import cache

from elections.models import Election
from .base import AdapterResult, ResultRow, StateResultsAdapter
from .registry import register

logger = logging.getLogger(__name__)

_ELECTIONSTATS_BASE = "https://electionstats.state.ma.us"
_CACHE_TTL = 86400 * 30  # 30 days
_TIMEOUT = 60

# Synthetic tally labels that are not real candidates
_TALLY_LABELS = frozenset({"All Others", "Blanks", "Total Votes Cast", "Write-In"})

# CSV column offset: first 3 columns are City/Town + 2 placeholders
_DATA_COL_OFFSET = 3


@register
class MassachusettsAdapter(StateResultsAdapter):
    state = "MA"

    def fetch_results(self, election_date, election_id: int) -> AdapterResult:
        try:
            election = Election.objects.get(pk=election_id)
        except Election.DoesNotExist:
            logger.error("ma_sos.adapter.missing_election pk=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes=f"Election pk={election_id} not found",
            )

        electionstats_id = (election.source_metadata or {}).get("electionstats_id")
        if not electionstats_id:
            logger.warning(
                "ma_sos.adapter.no_electionstats_id election=%s pk=%d",
                election.source_id, election_id,
            )
            return AdapterResult(
                rows=[],
                source_url="",
                mapping_confidence="none",
                notes="No electionstats_id in election.source_metadata",
            )

        csv_url = f"{_ELECTIONSTATS_BASE}/elections/download/{electionstats_id}/precincts_include:0/"

        try:
            resp = requests.get(csv_url, timeout=_TIMEOUT, headers={"User-Agent": "CivicMirror/1.0"})
            resp.raise_for_status()
            csv_bytes = resp.content
        except requests.RequestException as exc:
            logger.error("ma_sos.adapter.csv_fetch_error id=%s: %s", electionstats_id, exc)
            return AdapterResult(
                rows=[],
                source_url=csv_url,
                mapping_confidence="none",
                notes=f"CSV fetch failed: {exc}",
            )

        # Version check via SHA-256 fingerprint
        new_hash = hashlib.sha256(csv_bytes).hexdigest()
        cache_key = f"ma_sos:hash:{election_id}"
        cached_hash = cache.get(cache_key)

        if cached_hash == new_hash:
            logger.debug("ma_sos.adapter.unchanged election_id=%d", election_id)
            return AdapterResult(
                rows=[],
                source_url=csv_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=new_hash,
            )

        rows = _parse_election_csv(csv_bytes, csv_url)

        cache.set(cache_key, new_hash, _CACHE_TTL)

        logger.info(
            "ma_sos.adapter.fetched election_id=%d rows=%d",
            election_id, len(rows),
        )

        return AdapterResult(
            rows=rows,
            source_url=csv_url,
            mapping_confidence="full",
            source_version=new_hash,
        )


# ---------------------------------------------------------------------------
# CSV parsing helpers
# ---------------------------------------------------------------------------

def _parse_election_csv(csv_bytes: bytes, source_url: str) -> list[ResultRow]:
    """
    Parse an electionstats election results CSV into ResultRow objects.

    CSV structure:
      Row 0: "City/Town",,"","Candidate A","Candidate B",...,"All Others","Blanks","Total Votes Cast"
      Row 1: "",,"","Democratic","Republican",...
      Data rows: "Abington",,"","4,714","4,639",...
      Final row: "TOTALS",,"","2,126,518",...

    We emit one ResultRow per candidate per town. The TOTALS row (statewide aggregate)
    is included with jurisdiction_fragment="STATEWIDE". Tally labels (All Others, Blanks,
    Total Votes Cast) are emitted as is_write_in_aggregate=True / option_label rows.
    """
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)

    if len(all_rows) < 3:
        logger.warning("ma_sos.adapter.csv_too_short url=%s rows=%d", source_url, len(all_rows))
        return []

    header_row = all_rows[0]
    party_row = all_rows[1]

    # Build candidate metadata from header and party rows
    candidates: list[dict] = []
    for col_idx in range(_DATA_COL_OFFSET, len(header_row)):
        name = header_row[col_idx].strip().replace("\n", " ").replace("\r", "")
        if not name:
            continue
        party = party_row[col_idx].strip() if col_idx < len(party_row) else ""
        candidates.append({"name": name, "party": party, "col_idx": col_idx})

    rows: list[ResultRow] = []

    for data_row in all_rows[2:]:
        if not data_row or not data_row[0].strip():
            continue

        town = data_row[0].strip()
        is_totals = town.upper() == "TOTALS"
        jurisdiction_fragment = "STATEWIDE" if is_totals else town

        for cand in candidates:
            col_idx = cand["col_idx"]
            if col_idx >= len(data_row):
                continue
            vote_count = _parse_vote_count(data_row[col_idx])
            name = cand["name"]
            is_tally = name in _TALLY_LABELS

            rows.append(ResultRow(
                candidate_name=None if is_tally else name,
                option_label=name if is_tally else None,
                vote_count=vote_count,
                vote_pct=None,
                is_winner=None,
                result_type="official",
                office_title=None,  # caller matches against Race.office_title
                is_write_in_aggregate=(name == "All Others"),
                jurisdiction_fragment=jurisdiction_fragment,
                raw={
                    "town": town,
                    "party": cand["party"],
                    "col_idx": col_idx,
                },
            ))

    return rows


def _parse_vote_count(raw: str) -> int:
    """Parse a potentially comma-formatted vote count string to int."""
    cleaned = raw.strip().replace(",", "").replace('"', "")
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0

"""
Massachusetts results adapter using electionstats.state.ma.us CSV downloads.

All electionstats results are post-certification data — result_type is always "official".

Election electionstats_id is stored in Election.source_metadata["electionstats_id"]
and is populated programmatically by the sync_ma_elections task.

A partisan primary is split across multiple Races that share one canonical
Election (see integrations.ma_sos.mappers.contest_variant_key) — each party's
results live on their own electionstats CSV under that Race's own
electionstats_id (Race.source_metadata["electionstats_id"]). When a given
election has more than one such Race, fetch_results fetches each party's CSV
separately and tags every row with contest_code=str(electionstats_id) so
results.tasks._process_race_results routes rows to the correct Race instead
of applying every row to every race sharing the election. Elections with a
single Race (general elections, unsplit/nonpartisan primaries, or elections
whose Races haven't synced yet) keep the original single-CSV behavior, keyed
off Election.source_metadata["electionstats_id"].

Version cache key: "ma_sos:hash:{election_id}"
Cache value:       SHA-256 hex digest of the CSV body (or, for a split
                    primary, of all fetched CSV bodies concatenated in
                    electionstats_id order).
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
from typing import Optional

import requests
from django.core.cache import cache

from elections.models import Election, Race

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

        # A split primary has multiple Races sharing this Election, each with
        # its own electionstats_id (its own party's CSV). Collect the distinct
        # ids across the election's Races; more than one means a split fetch
        # is needed. Races without an electionstats_id (not yet synced, or a
        # non-ma_sos source) are ignored here.
        race_stats_ids: dict[int, list[int]] = {}
        for race in Race.objects.filter(election=election, source=Race.Source.MA_SOS):
            sid = (race.source_metadata or {}).get("electionstats_id")
            if sid:
                race_stats_ids.setdefault(int(sid), []).append(race.pk)

        if len(race_stats_ids) > 1:
            return self._fetch_split(election_id, sorted(race_stats_ids))

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

        try:
            csv_bytes, csv_url = self._download_csv(electionstats_id)
        except requests.RequestException as exc:
            logger.error("ma_sos.adapter.csv_fetch_error id=%s: %s", electionstats_id, exc)
            return AdapterResult(
                rows=[],
                source_url=f"{_ELECTIONSTATS_BASE}/elections/download/{electionstats_id}/precincts_include:0/",
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

        rows = _parse_election_csv(csv_bytes, csv_url, contest_code=str(electionstats_id))

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

    def _download_csv(self, electionstats_id: int) -> tuple[bytes, str]:
        csv_url = f"{_ELECTIONSTATS_BASE}/elections/download/{electionstats_id}/precincts_include:0/"
        resp = requests.get(csv_url, timeout=_TIMEOUT, headers={"User-Agent": "CivicMirror/1.0"})
        resp.raise_for_status()
        return resp.content, csv_url

    def _fetch_split(self, election_id: int, electionstats_ids: list[int]) -> AdapterResult:
        """
        Fetch and combine each party's CSV for a primary split across
        multiple Races. Every row is tagged raw["contest_code"] = str(that
        CSV's electionstats_id), matching Race.source_metadata["contest_code"]
        (set in integrations.ma_sos.mappers.map_race) so
        results.tasks._process_race_results routes each party's rows to its
        own Race instead of applying every row to every race.
        """
        all_rows: list[ResultRow] = []
        csv_bodies: list[bytes] = []
        urls: list[str] = []

        for stats_id in electionstats_ids:
            try:
                csv_bytes, csv_url = self._download_csv(stats_id)
            except requests.RequestException as exc:
                logger.error("ma_sos.adapter.csv_fetch_error id=%s: %s", stats_id, exc)
                return AdapterResult(
                    rows=[],
                    source_url="; ".join(urls),
                    mapping_confidence="none",
                    notes=f"CSV fetch failed for electionstats_id={stats_id}: {exc}",
                )
            csv_bodies.append(csv_bytes)
            urls.append(csv_url)
            rows = _parse_election_csv(csv_bytes, csv_url, contest_code=str(stats_id))
            all_rows.extend(rows)

        # Combined fingerprint over every fetched CSV, in electionstats_id order.
        new_hash = hashlib.sha256(b"".join(csv_bodies)).hexdigest()
        cache_key = f"ma_sos:hash:{election_id}"
        cached_hash = cache.get(cache_key)
        source_url = "; ".join(urls)

        if cached_hash == new_hash:
            logger.debug("ma_sos.adapter.unchanged election_id=%d (split)", election_id)
            return AdapterResult(
                rows=[],
                source_url=source_url,
                mapping_confidence="full",
                unchanged=True,
                source_version=new_hash,
            )

        cache.set(cache_key, new_hash, _CACHE_TTL)

        logger.info(
            "ma_sos.adapter.fetched_split election_id=%d electionstats_ids=%s rows=%d",
            election_id, electionstats_ids, len(all_rows),
        )

        return AdapterResult(
            rows=all_rows,
            source_url=source_url,
            mapping_confidence="full",
            source_version=new_hash,
        )


# ---------------------------------------------------------------------------
# CSV parsing helpers
# ---------------------------------------------------------------------------

def _parse_election_csv(csv_bytes: bytes, source_url: str, contest_code: str = "") -> list[ResultRow]:
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

    contest_code, when passed by _fetch_split for a party-split primary, is
    this CSV's own electionstats_id — carried into each row's raw dict so
    results.tasks._process_race_results can match it against the owning
    Race's source_metadata["contest_code"].
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
                    **({"contest_code": contest_code} if contest_code else {}),
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

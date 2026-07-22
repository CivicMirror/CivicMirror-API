"""
Parser for BPro TotalVote's election-wide CSV export (New Mexico SOS).

New Mexico runs two unrelated public election-data systems (see
docs/state-research/NM/NM-Election_ResearchV4.md): BPro TotalVote ENR for
live/current results (this module) and Civera ElectionStats for historical
GraphQL-backed data (deferred, tracked in GitHub issue #84).

The election-wide CSV (resultsCSV.aspx?text=All&type=STATE&map=CTY&eid=...)
gives one row per (race, candidate-or-ballot-choice) with combined
(non-precinct) vote totals for every race in one election — no aggregation
across files is needed, unlike Maryland's per-county CSVs.

Three things this parser must get right that Maryland/Missouri didn't need to:

1. Office-title collisions: NM's captured election is hyper-local (mayors,
   municipal judges, school boards, city councilors across dozens of towns).
   The same RaceName (e.g. "Mayor") is reused by dozens of unrelated
   RaceIDs. office_title is qualified as "{AreaNum} — {RaceName}" (falling
   back to bare RaceName when AreaNum is blank) to avoid
   results.tasks._bootstrap_races_from_results collapsing unrelated cities'
   races into one, mirroring results/adapters/ct.py's _build_office_town_map
   precedent for the identical problem.
2. Generic Yes/No choice IDs: CandidateID 9001/9002 are reused across every
   ballot-measure row in the file to mean "Yes"/"No" — routed to
   option_label, never candidate_name, and scoped per-row by contest_code
   (RaceID) since the ID itself is not globally unique to one measure.
3. Long ballot-measure titles: RaceName for a ballot measure is the full
   legal question text, not a short label — 108 of the 599 real races in
   the captured election have a RaceName exceeding Race.office_title's
   255-char CharField limit (up to 636 chars observed). SQLite (used by
   local/CI-less test runs) does not enforce CharField length, so this only
   surfaces against a real Postgres database — office_title is truncated to
   fit. Truncation cannot reintroduce the office-title collision risk from
   point 1: contest_code-based source_identity (not the office_title string)
   is what actually disambiguates races on the bootstrap path (see
   test_bootstrap_creates_separate_races_for_colliding_office_titles's
   docstring), and every row here always carries a real, distinct
   contest_code.

Percentages arrive as a 0-1 fraction; ResultRow.vote_pct is stored on a
0-100 scale (repo convention, see results/adapters/me.py) — multiplied here.

result_type is "unofficial": BPro is a live/election-night system, and the
research doc documents a real label inconsistency for this exact election
(public page says "Official Results", the Excel export for the same
election says "Unofficial Special Election Results") — this matches other
live-source adapters (fl.py, wa.py, pa.py, mn.py, nj.py, tx.py), not
Maryland/Missouri's "official" (both pull from certified archives).

No Winner column exists in this CSV — is_winner is always None.
"""
from __future__ import annotations

import csv
import io

from .base import ResultRow

_YES_NO_CANDIDATE_IDS = frozenset({"9001", "9002"})
_MAX_OFFICE_TITLE_LENGTH = 255
_TRUNCATION_SUFFIX = "…"


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _truncate_office_title(title: str) -> str:
    """Race.office_title is a CharField(max_length=255) — some NM ballot
    measures' full legal question text runs well past that (up to 636 chars
    observed in the real captured data). SQLite doesn't enforce CharField
    length, so this only bites against a real Postgres database."""
    if len(title) <= _MAX_OFFICE_TITLE_LENGTH:
        return title
    return title[: _MAX_OFFICE_TITLE_LENGTH - len(_TRUNCATION_SUFFIX)] + _TRUNCATION_SUFFIX


def _parse_int(value: str | None) -> int:
    cleaned = _clean(value)
    if not cleaned:
        return 0
    try:
        return int(cleaned)
    except ValueError:
        return 0


def parse_election_wide_csv(csv_text: str) -> list[ResultRow]:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[ResultRow] = []

    for raw_row in reader:
        race_id = _clean(raw_row.get("RaceID"))
        race_name = _clean(raw_row.get("RaceName"))
        area_num = _clean(raw_row.get("AreaNum"))
        candidate_id = _clean(raw_row.get("CandidateID"))
        candidate_name = _clean(raw_row.get("CandidateName"))
        party_code = _clean(raw_row.get("PartyCode"))

        if not race_id or not race_name:
            continue

        office_title = f"{area_num} — {race_name}" if area_num else race_name
        office_title = _truncate_office_title(office_title)
        is_yes_no = candidate_id in _YES_NO_CANDIDATE_IDS

        pct_raw = _clean(raw_row.get("CandidatePercentage"))
        try:
            vote_pct = float(pct_raw) * 100 if pct_raw else None
        except ValueError:
            vote_pct = None

        rows.append(
            ResultRow(
                candidate_name=None if is_yes_no else candidate_name,
                option_label=candidate_name if is_yes_no else None,
                vote_count=_parse_int(raw_row.get("CandidateVotes")),
                vote_pct=vote_pct,
                is_winner=None,
                result_type="unofficial",
                office_title=office_title,
                is_write_in_aggregate=False,
                jurisdiction_fragment=area_num,
                raw={"contest_code": race_id, "party_code": party_code},
            )
        )

    return rows

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

Two things this parser must get right that Maryland/Missouri didn't need to:

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


def _clean(value: str | None) -> str:
    return (value or "").strip()


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

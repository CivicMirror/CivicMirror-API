from __future__ import annotations

from collections.abc import Iterator


def iter_media_export_rows(payload: dict) -> Iterator[dict]:
    """Yield flattened state, county, and precinct rows from a GA media export."""
    results = payload.get("results") or {}
    yield from _iter_ballot_items(results.get("ballotItems") or [], level="state", county="")

    for local_result in payload.get("localResults") or []:
        county = (local_result.get("name") or "").strip()
        yield from _iter_ballot_items(local_result.get("ballotItems") or [], level="county", county=county)


def _iter_ballot_items(ballot_items: list[dict], *, level: str, county: str) -> Iterator[dict]:
    for contest in ballot_items:
        contest_id = str(contest.get("id") or "")
        contest_name = str(contest.get("name") or "")
        for option in contest.get("ballotOptions") or []:
            base_row = _row(
                level=level,
                county=county,
                contest_id=contest_id,
                contest_name=contest_name,
                option=option,
            )
            yield base_row

            if level == "county":
                for precinct in option.get("precinctResults") or []:
                    yield {
                        **base_row,
                        "level": "precinct",
                        "precinct_id": str(precinct.get("id") or ""),
                        "precinct_name": str(precinct.get("name") or ""),
                        "vote_count": _safe_int(precinct.get("voteCount")),
                        "reporting_status": str(precinct.get("reportingStatus") or ""),
                    }


def _row(*, level: str, county: str, contest_id: str, contest_name: str, option: dict) -> dict:
    candidate_id = str(option.get("id") or "")
    return {
        "level": level,
        "county": county if level != "state" else "",
        "precinct_id": "",
        "precinct_name": "",
        "contest_id": contest_id,
        "contest_name": contest_name,
        "candidate_id": candidate_id,
        "candidate_name": str(option.get("name") or ""),
        "party": str(option.get("politicalParty") or ""),
        "vote_count": _safe_int(option.get("voteCount")),
        "reporting_status": "",
        "scoped_option_id": f"{contest_id}:{candidate_id}",
    }


def _safe_int(value) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0

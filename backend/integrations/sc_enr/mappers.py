"""
Mappers for SC ENR elections.json data → ENRElection model fields,
and election linking logic (ENRElection ↔ elections.Election).
"""
import logging
from datetime import date, datetime

from elections.models import Election

from .models import ENRElection

logger = logging.getLogger(__name__)

# ENR date format from elections.json: "MM/DD/YYYY HH:MM:SS"
_ENR_DATE_FORMAT = "%m/%d/%Y %H:%M:%S"


def parse_enr_date(date_str: str) -> date:
    """Parse ENR Date field ("MM/DD/YYYY HH:MM:SS") to a Python date."""
    try:
        return datetime.strptime(date_str.strip(), _ENR_DATE_FORMAT).date()
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Cannot parse ENR date {date_str!r}: {exc}") from exc


def map_enr_election(entry: dict) -> dict:
    """
    Map a single elections.json entry to ENRElection field values.

    Returns a dict suitable for ENRElection(**fields) or update_or_create(defaults=...).
    Does not include 'election' FK or 'enr_resolved_url' — those are set separately.
    """
    eid: int = entry["EID"]
    county: str | None = entry.get("County") or None  # treat "" as null
    election_date = parse_enr_date(entry["Date"])
    scope = ENRElection.Scope.COUNTY if county else ENRElection.Scope.STATE

    if county:
        base_path = f"SC/{county.replace(' ', '_')}/{eid}/"
    else:
        base_path = f"SC/{eid}/"
    enr_base_url = f"https://www.enr-scvotes.org/{base_path}"

    return {
        "election_name": entry.get("ElectionName", "").strip(),
        "election_date": election_date,
        "scope": scope,
        "county": county,
        "eid": eid,
        "enr_base_url": enr_base_url,
    }


def attempt_election_link(
    enr_election: ENRElection,
) -> tuple[Election | None, str]:
    """
    Attempt to link a state-level ENRElection to an existing elections.Election
    by matching (election_date, state="SC").

    Returns (election_obj, link_confidence) where confidence is:
      "auto"      — exactly one match found; safe to link automatically
      "ambiguous" — zero or multiple matches; manual admin review needed

    Only state-level (scope="state", county=null) entries are linked here.
    County-level entries always return (None, "ambiguous") — they are stored for
    future reference but not linked to Election records.
    """
    if enr_election.scope != ENRElection.Scope.STATE:
        return None, ENRElection.LinkConfidence.AMBIGUOUS

    matches = list(
        Election.objects.filter(
            election_date=enr_election.election_date,
            state="SC",
        )
    )

    if len(matches) == 1:
        logger.debug(
            "sc_enr.link_election eid=%d linked election_pk=%d",
            enr_election.eid,
            matches[0].pk,
        )
        return matches[0], ENRElection.LinkConfidence.AUTO

    if len(matches) == 0:
        logger.warning(
            "sc_enr.link_election.no_match eid=%d date=%s — "
            "no SC Election found for this date; manual link required",
            enr_election.eid,
            enr_election.election_date,
        )
    else:
        logger.warning(
            "sc_enr.link_election.ambiguous eid=%d date=%s — "
            "%d SC Elections match; manual link required: pks=%s",
            enr_election.eid,
            enr_election.election_date,
            len(matches),
            [e.pk for e in matches],
        )

    return None, ENRElection.LinkConfidence.AMBIGUOUS

"""Shared NC event identity, source hints and pre-persistence result partitioning."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from aggregation.identity import election_canonical_key
from elections.models import Election, Race

from .classification import RULE_VERSION, NcClassification, classify_nc_contest, normalized_title
from .client import _results_zip_url

CLASSIFICATION = "nc_classification"
CONTAINER = "nc_classification_container"
RETIRED = "nc_classification_retired"


def event_key(day: date, classification: NcClassification) -> str:
    if not classification.resolved:
        raise ValueError("Held classification cannot materialize an election")
    return election_canonical_key(
        "NC", classification.election_type, day, classification.jurisdiction_level, classification.event_group
    )


def event_metadata(classification: NcClassification) -> dict:
    data = classification.to_dict()
    if not classification.event_group:
        data.update(jurisdiction_kind="state", jurisdiction_key="state:NC", jurisdiction_name="North Carolina")
    return data


@transaction.atomic
def ensure_event(day: date, classification: NcClassification):
    from aggregation import ingest

    key = event_key(day, classification)
    existing = (
        Election.objects.select_for_update()
        .filter(Q(canonical_key=key) | Q(state="NC", source_metadata__nc_event_key=key))
        .first()
    )
    # Legacy imports/tests can have an unkeyed regular state event. Adopt only
    # a unique exact type/date/jurisdiction match; never choose a same-date sibling.
    if existing is None and not classification.event_group:
        unkeyed = list(
            Election.objects.select_for_update().filter(
                state="NC",
                election_date=day,
                election_type=classification.election_type,
                jurisdiction_level=classification.jurisdiction_level,
                canonical_key__isnull=True,
            )
        )
        if len(unkeyed) == 1:
            existing = unkeyed[0]
            # Keep the e{pk} race-key namespace intact; an explicit repair may
            # later change it. A virtual event key permits stable source lookup.
            existing.source_metadata = {**existing.source_metadata, "nc_event_key": key}
            existing.save(update_fields=["source_metadata"])
    meta = dict(existing.source_metadata or {}) if existing else {}
    if meta.get(CONTAINER) or meta.get(RETIRED):
        return existing, False
    meta.update(
        {
            CLASSIFICATION: event_metadata(classification),
            "nc_date_str": day.strftime("%Y_%m_%d"),
            "results_url": _results_zip_url(day.strftime("%Y_%m_%d")),
        }
    )
    identity = {
        "state": "NC",
        "election_type": classification.election_type,
        "election_date": day,
        "jurisdiction_level": classification.jurisdiction_level,
        "contest_group": classification.event_group,
    }
    source_id = "nc_sbe_" + (
        day.strftime("%Y_%m_%d") if not classification.event_group else hashlib.sha256(key.encode()).hexdigest()[:24]
    )
    scope = classification.jurisdiction_name if classification.jurisdiction_level == "local" else "North Carolina"
    label = classification.phase.replace("_", " ").title() + " Election"
    if classification.special_context:
        label = "Special " + label
    return ingest.ingest_election(
        source="nc_sbe",
        source_id=source_id,
        identity=identity,
        fields={
            "name": f"{day.year} {scope} {label} ({day.isoformat()})",
            "status": Election.Status.UPCOMING if day > timezone.localdate() else Election.Status.RESULTS_PENDING,
            "source_metadata": meta,
        },
    )


def filing_hints(day: date) -> dict:
    values = {}
    for metadata in Election.objects.filter(state="NC", election_date=day).values_list("source_metadata", flat=True):
        for hint in (metadata or {}).get("nc_filing_hints", []):
            key = (hint["title"], hint["party"], hint["county"])
            value = hint["is_unexpired"]
            values[key] = value if key not in values or values[key] == value else "conflicting_filing_flags"
    for race in (
        Race.objects.filter(election__state="NC", election__election_date=day)
        .exclude(source_metadata__has_key="nc_superseded_by")
        .only("office_title", "party", "source_metadata")
    ):
        meta = race.source_metadata or {}
        if "is_unexpired" not in meta or meta["is_unexpired"] is None:
            continue
        key = (
            normalized_title(meta.get("contest_name") or race.office_title),
            (meta.get("party_contest") or race.party or "").upper(),
            (meta.get("county") or "").upper(),
        )
        value = meta["is_unexpired"]
        if key in values and values[key] != value:
            values[key] = "conflicting_filing_flags"
        else:
            values[key] = value
    return values


def discover_filing_events(client, known_dates: set[date], minimum_year: int) -> tuple[int, int, int]:
    """Materialize current/future source events without bootstrapping any races.

    Historical identity repair remains explicit. Candidate contact fields never
    enter source metadata; only title/party/county/unexpired routing hints do.
    """
    from .client import parse_candidate_listing_csv
    from .mappers import parse_candidate_filing_date

    created = updated = held = 0
    groups = {}
    for year in sorted({d.year for d in known_dates if d.year >= minimum_year}):
        key = client.list_candidate_filing_csv_key(str(year))
        if not isinstance(key, str) or not key:
            continue
        for row in parse_candidate_listing_csv(client.fetch_candidate_filing_csv(key)):
            day = parse_candidate_filing_date(row.get("election_dt", ""))
            if day not in known_dates or day.year < minimum_year:
                continue
            classification = classify_nc_contest(
                day,
                row.get("contest_name", ""),
                county=row.get("county_name", ""),
                party_contest=row.get("party_contest", ""),
                is_unexpired=row.get("is_unexpired"),
            )
            if not classification.resolved:
                held += 1
                continue
            group = groups.setdefault(event_key(day, classification), (day, classification, {}))
            hint = {
                "title": normalized_title(row.get("contest_name", "")),
                "party": row.get("party_contest", "").strip().upper(),
                "county": row.get("county_name", "").strip().upper()
                if classification.jurisdiction_kind == "county"
                else "",
                "is_unexpired": {"TRUE": True, "FALSE": False}.get((row.get("is_unexpired") or "").strip().upper()),
            }
            group[2][json.dumps(hint, sort_keys=True)] = hint
    for day, classification, hints in groups.values():
        election, was_created = ensure_event(day, classification)
        metadata = {**election.source_metadata, "nc_filing_hints": list(hints.values())}
        Election.objects.filter(pk=election.pk).update(source_metadata=metadata)
        created += was_created
        updated += not was_created
    return created, updated, held


def classify_result_row(day: date, row, hints: dict | None = None) -> NcClassification:
    raw = row.raw or {}
    title = normalized_title(row.office_title)
    party = raw.get("party_code", "")
    county = raw.get("county", "").upper()
    hints = hints or {}
    hint = hints.get((title, party, county), hints.get((title, party, "")))
    return classify_nc_contest(
        day,
        row.office_title,
        county=county,
        party_contest=party,
        is_unexpired=hint,
        identity_verified=raw.get("nc_identity_verified"),
    )


def filter_result_rows(election, rows):
    meta = election.source_metadata or {}
    if meta.get(RETIRED) or meta.get(CONTAINER):
        return []
    if CLASSIFICATION not in meta:
        return rows  # Legacy records require the explicit source-qualified repair.
    hints = filing_hints(election.election_date)
    selected = []
    for row in rows:
        classification = classify_result_row(election.election_date, row, hints)
        target_key = election.canonical_key or meta.get("nc_event_key")
        if classification.resolved and event_key(election.election_date, classification) == target_key:
            selected.append(dataclasses.replace(row, raw={**(row.raw or {}), CLASSIFICATION: classification.to_dict()}))
    return selected


def routing_version(election) -> str:
    hints = filing_hints(election.election_date)
    payload = [
        RULE_VERSION,
        (election.source_metadata or {}).get(CLASSIFICATION),
        sorted((list(key), value) for key, value in hints.items()),
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]

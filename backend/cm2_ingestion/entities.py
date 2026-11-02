# backend/cm2_ingestion/entities.py
from cm2_core.models import SourceArtifact
from cm2_elections.models import Contest, Election, Jurisdiction, Office

from .contracts import ContestRecord, JurisdictionRecord, OfficeRecord


def upsert_public(model, public_id: str, values: dict):
    instance, created = model.objects.get_or_create(public_id=public_id, defaults=values)
    if created:
        return instance, True, False

    changed_fields = []
    for field_name, value in values.items():
        if getattr(instance, field_name) != value:
            setattr(instance, field_name, value)
            changed_fields.append(field_name)
    if changed_fields:
        instance.save(update_fields=[*changed_fields, "updated_at"])
    return instance, False, bool(changed_fields)


def upsert_natural(model, lookup: dict, values: dict):
    instance, created = model.objects.get_or_create(**lookup, defaults=values)
    if created:
        return instance, True, False

    changed_fields = []
    for field_name, value in values.items():
        if getattr(instance, field_name) != value:
            setattr(instance, field_name, value)
            changed_fields.append(field_name)
    if changed_fields:
        instance.save(update_fields=[*changed_fields, "updated_at"])
    return instance, False, bool(changed_fields)


def track(
    *,
    category: str,
    instance,
    created: bool,
    updated: bool,
    counts: dict[str, int],
    details: dict,
) -> None:
    if created:
        counts[f"{category}_created"] += 1
        details["created"][category].append(instance.public_id)
    elif updated:
        counts[f"{category}_updated"] += 1
        details["updated"][category].append(instance.public_id)


def persist_jurisdictions(
    *,
    artifact: SourceArtifact,
    records: tuple[JurisdictionRecord, ...],
    counts: dict[str, int],
    details: dict,
) -> dict[str, Jurisdiction]:
    record_by_id = {record.public_id: record for record in records}
    persisted: dict[str, Jurisdiction] = {}

    def persist(record: JurisdictionRecord) -> Jurisdiction:
        if record.public_id in persisted:
            return persisted[record.public_id]
        parent = persist(record_by_id[record.parent_public_id]) if record.parent_public_id else None
        jurisdiction, created, updated = upsert_public(
            Jurisdiction,
            record.public_id,
            {
                "name": record.name,
                "classification": record.classification,
                "state": record.state,
                "parent": parent,
                "active_start": record.active_start,
                "active_end": record.active_end,
                "record_status": record.record_status,
                "source_artifact": artifact,
                "source_key": record.source_key,
            },
        )
        persisted[record.public_id] = jurisdiction
        track(category="jurisdictions", instance=jurisdiction, created=created, updated=updated, counts=counts, details=details)
        return jurisdiction

    for jurisdiction_record in records:
        persist(jurisdiction_record)
    return persisted


def persist_offices(
    *,
    artifact: SourceArtifact,
    records: tuple[OfficeRecord, ...],
    jurisdictions: dict[str, Jurisdiction],
    counts: dict[str, int],
    details: dict,
) -> dict[str, Office]:
    offices: dict[str, Office] = {}
    for record in records:
        office, created, updated = upsert_public(
            Office,
            record.public_id,
            {
                "jurisdiction": jurisdictions[record.jurisdiction_public_id],
                "canonical_name": record.canonical_name,
                "role": record.role,
                "default_term_months": record.default_term_months,
                "positions": record.positions,
                "record_status": record.record_status,
                "source_artifact": artifact,
                "source_key": record.source_key,
            },
        )
        offices[record.public_id] = office
        track(category="offices", instance=office, created=created, updated=updated, counts=counts, details=details)
    return offices


def persist_contests(
    *,
    artifact: SourceArtifact,
    records: tuple[ContestRecord, ...],
    elections: dict[str, Election],
    offices: dict[str, Office],
    counts: dict[str, int],
    details: dict,
) -> dict[str, Contest]:
    contests: dict[str, Contest] = {}
    for record in records:
        contest, created, updated = upsert_public(
            Contest,
            record.public_id,
            {
                "election": elections[record.election_public_id],
                "office": offices[record.office_public_id],
                "party_contest": record.party_contest,
                "vote_for": record.vote_for,
                "is_partisan": record.is_partisan,
                "is_unexpired": record.is_unexpired,
                "lifecycle_status": record.lifecycle_status,
                "result_status": record.result_status,
                "source_artifact": artifact,
                "source_key": record.source_key,
            },
        )
        contests[record.public_id] = contest
        track(category="contests", instance=contest, created=created, updated=updated, counts=counts, details=details)
    return contests

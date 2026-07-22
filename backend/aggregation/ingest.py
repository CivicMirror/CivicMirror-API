"""
Normalize-on-write merge engine.

Adapters call ingest_election/ingest_race/ingest_candidate with their source
name and normalized field dicts. Each field is written only when the incoming
source out-ranks the field's current provenance owner (see precedence.resolve_rank).

Each ingest function returns ``(instance, created)`` where ``created`` is True if
the canonical row did not exist before this call. Adapters use it for accurate
SyncLog accounting; previously they inferred create/update from
``contributing_sources == [source]`` which collapsed re-syncs of a single-source
record into ``created``.
"""
import logging

from django.db import transaction
from django.utils import timezone

from elections.models import Candidate, Election, ElectionSourceLink, Race

from .identity import election_canonical_key, name_match_key, normalize_party, race_canonical_key
from .precedence import field_group_for, resolve_rank

logger = logging.getLogger(__name__)


def _apply_fields(instance, state, source, fields):
    """Write each field if `source` out-ranks the current owner. Returns changed field names."""
    provenance = instance.field_provenance or {}
    changed = []
    for name, value in fields.items():
        group = field_group_for(name)
        incoming = resolve_rank(state, group, source)
        owner = provenance.get(name)
        owner_rank = resolve_rank(state, group, owner) if owner else float("inf")
        if owner is None or incoming <= owner_rank:
            setattr(instance, name, value)
            provenance[name] = source
            changed.append(name)
    instance.field_provenance = provenance
    return changed


def _add_source(instance, source):
    if not hasattr(instance, "contributing_sources"):
        return
    sources = list(instance.contributing_sources or [])
    if source not in sources:
        sources.append(source)
        instance.contributing_sources = sources


@transaction.atomic
def ingest_election(*, source, source_id, identity, fields):
    state = identity.get("state")
    election_date = identity.get("election_date")
    election_type = identity.get("election_type")
    jurisdiction_level = identity.get("jurisdiction_level")

    if not (state and election_date and election_type and jurisdiction_level):
        # Cannot form a canonical key — keep as its own row, flagged for review.
        # Look it up via ElectionSourceLink so retries from the same
        # (source, source_id) reuse the existing row rather than violating the
        # unique constraint on Election.source_id or producing orphan duplicates.
        link = ElectionSourceLink.objects.filter(source=source, source_id=source_id).first()
        if link is not None:
            election = link.election
            link.last_synced_at = timezone.now()
            link.save(update_fields=["last_synced_at"])
            created = False
        else:
            election = Election.objects.create(
                name=fields.get("name", "Needs review"),
                election_date=election_date or timezone.localdate(),
                election_type=election_type or Election.ElectionType.OTHER,
                jurisdiction_level=jurisdiction_level or Election.JurisdictionLevel.STATE,
                state=state, source_id=source_id, needs_review=True,
            )
            ElectionSourceLink.objects.create(
                election=election, source=source, source_id=source_id,
                last_synced_at=timezone.now(),
            )
            created = True
        _add_source(election, source)
        election.save(update_fields=["contributing_sources"])
        logger.warning("aggregation.election.needs_review source=%s source_id=%s", source, source_id)
        return election, created

    key = election_canonical_key(state, election_type, election_date, jurisdiction_level)
    election = Election.objects.select_for_update().filter(canonical_key=key).first()
    created = election is None
    if election is None:
        # Migrated sources leave Election.source_id NULL; the per-source id is
        # recorded on ElectionSourceLink below.
        election = Election(
            canonical_key=key, state=state,
            election_date=election_date, election_type=election_type,
            jurisdiction_level=jurisdiction_level, name=fields.get("name", ""),
        )

    _apply_fields(election, state, source, {**fields, "election_date": election_date})
    _add_source(election, source)
    election.last_synced_at = timezone.now()
    election.save()

    ElectionSourceLink.objects.update_or_create(
        election=election, source=source,
        defaults={
            "source_id": source_id,
            "results_url": fields.get("results_url", "") or "",
            "last_synced_at": timezone.now(),
        },
    )
    return election, created


@transaction.atomic
def ingest_race(*, election, source, identity, fields):
    state = election.state or "*"
    office_title = identity["office_title"]
    ocd = identity.get("ocd_division_id", "") or ""
    race_type = identity["race_type"]
    contest_variant = identity.get("contest_variant", "") or ""
    key = race_canonical_key(
        election.canonical_key or f"e{election.pk}", office_title, ocd, race_type, contest_variant,
    )

    race = Race.objects.select_for_update().filter(canonical_key=key).first()
    created = race is None
    if race is None:
        race = Race(
            canonical_key=key, election=election, office_title=office_title,
            ocd_division_id=ocd, race_type=race_type,
            jurisdiction=fields.get("jurisdiction", ""),
            geography_scope=fields.get("geography_scope", ""),
            source=source,
        )

    _apply_fields(race, state, source, fields)
    _add_source(race, source)
    # Representative `source` = highest-precedence contributing source for identity group.
    race.source = min(
        race.contributing_sources,
        key=lambda s: resolve_rank(state, "identity", s),
    )
    race.last_synced_at = timezone.now()
    race.save()
    return race, created


@transaction.atomic
def ingest_candidate(*, race, source, name, party, fields):
    norm_name = name_match_key(name)
    norm_party = normalize_party(party)
    state = race.election.state or "*"

    match = None
    name_only_match = None
    # Order-independent match on (normalized name, normalized party); nonpartisan = name only.
    for cand in race.candidates.all():
        if name_match_key(cand.name) != norm_name:
            continue
        if name_only_match is None:
            name_only_match = cand
        if norm_party == "" or normalize_party(cand.party) == norm_party:
            match = cand
            break

    if match is None and name_only_match is not None:
        # unique_candidate_name_per_race only constrains (race, name), not party,
        # so a party that doesn't reconcile can never mean "a second candidate
        # with this exact name" — it means the source corrected/varied the
        # party spelling. Fall back to the name match rather than attempting a
        # second insert that the DB would reject outright.
        logger.warning(
            "ingest_candidate.party_mismatch race=%s name=%s existing_party=%r incoming_party=%r",
            race.pk, name, name_only_match.party, party,
        )
        match = name_only_match

    created = match is None
    if match is None:
        match = Candidate(race=race, name=name, party=party, normalized_party=norm_party)

    _apply_fields(match, state, source, {**fields, "party": party})
    _add_source(match, source)
    if not match.name:
        match.name = name
    # Reflect the precedence-winning party in normalized_party.
    match.normalized_party = normalize_party(match.party)
    match.save()
    return match, created

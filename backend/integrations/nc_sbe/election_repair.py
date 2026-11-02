"""No-write classification preview and fingerprint-checked NC event reparenting.

This does not merge contests, replace results, or resolve the historical identity
holds. Supported races move intact; unresolved components retain their records.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from aggregation.identity import name_match_key
from community.models import MockVote
from elections.models import Candidate, Election, ElectionSourceLink, MeasureOption, Race
from ops.models import SourceRecord
from results.models import OfficialResult
from results.nc_identity import contest_party
from results.nc_repair import _snapshot

from .classification import NcClassification, classify_nc_contest, normalized_title
from .event_identity import CLASSIFICATION, CONTAINER, RETIRED, ensure_event, event_key, event_metadata


class ClassificationConflict(ValueError):
    pass


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _scope(election):
    metadata = Election.objects.get(pk=election.pk, state="NC").source_metadata
    ids = {election.pk, *(metadata or {}).get("nc_classification_replacements", [])}
    return Election.objects.filter(pk__in=ids, state="NC").order_by("pk")


def source_hints(filing_rows, day):
    from .mappers import parse_candidate_filing_date

    hints = {}
    for row in filing_rows:
        if parse_candidate_filing_date(row.get("election_dt", "")) != day:
            continue
        classification = classify_nc_contest(
            day,
            row.get("contest_name", ""),
            county=row.get("county_name", ""),
            party_contest=row.get("party_contest", ""),
            is_unexpired=row.get("is_unexpired"),
        )
        key = (
            normalized_title(row.get("contest_name", "")),
            row.get("party_contest", "").strip().upper(),
            row.get("county_name", "").strip().upper() if classification.jurisdiction_kind == "county" else "",
        )
        value = {"TRUE": True, "FALSE": False}.get((row.get("is_unexpired") or "").strip().upper())
        if key in hints and hints[key] != value:
            hints[key] = "conflicting_filing_flags"
        else:
            hints[key] = value
    return hints


def _source_for(race, groups, title_index):
    meta = race.source_metadata or {}
    if meta.get("nc_contest_key"):
        return [group for key, group in groups.items() if key == meta["nc_contest_key"]]
    party = meta.get("party_contest") or contest_party(race.office_title)
    if not party and race.election.election_type in {"primary", "primary_runoff"}:
        party = race.party
    county = (meta.get("county") or "").upper()
    return [
        rows
        for rows in title_index.get((normalized_title(race.office_title), (party or "").upper()), [])
        if not county or county == (rows[0].raw or {}).get("county", "").upper()
    ]


def _votes_match(race, rows):
    expected = defaultdict(int)
    for row in rows:
        key = (
            "__write_in__"
            if row.is_write_in_aggregate
            else name_match_key(row.candidate_name or row.option_label or "")
        )
        expected[key] += row.vote_count or 0
    for result in race.official_results.all():
        if result.jurisdiction_fragment:
            continue
        key = (
            "__write_in__"
            if result.is_write_in_aggregate
            else name_match_key(
                result.candidate.name
                if result.candidate_id
                else result.measure_option.option_label
                if result.measure_option_id
                else ""
            )
        )
        if key not in expected or result.vote_count != expected[key]:
            return False
    return True


def build_classification_plan(election, filing_rows, result_rows, source_hashes) -> dict:
    from .event_identity import classify_result_row

    if election.state != "NC":
        raise ClassificationConflict("Only NC elections may be reconciled")
    scope = list(_scope(election))
    races = list(
        Race.objects.filter(election__in=scope)
        .select_related("election")
        .prefetch_related("official_results__candidate", "official_results__measure_option")
        .order_by("pk")
    )
    groups = defaultdict(list)
    for row in result_rows:
        key = (row.raw or {}).get("nc_contest_key")
        if key:
            groups[key].append(row)
    hints = source_hints(filing_rows, election.election_date)
    title_index = defaultdict(list)
    for rows in groups.values():
        title_index[(normalized_title(rows[0].office_title), (rows[0].raw or {}).get("party_code", ""))].append(rows)
    targets, moves, held = {}, [], []
    pre_election = election.election_date > timezone.localdate() or (
        election.election_date == timezone.localdate()
        and result_rows and not any((row.vote_count or 0) > 0 for row in result_rows)
    )
    for race in races:
        if (race.source_metadata or {}).get("nc_superseded_by"):
            continue
        matches = _source_for(race, groups, title_index)
        reason = None
        if len(matches) != 1:
            reason = "source_identity_missing_or_ambiguous"
        elif any((row.raw or {}).get("nc_vote_errors") for row in matches[0]):
            reason = "invalid_source_votes"
        elif not _votes_match(race, matches[0]):
            reason = "existing_source_vote_mismatch"
        elif pre_election and (
            any((row.vote_count or 0) != 0 for row in matches[0])
            or any((r.vote_count or 0) != 0 or r.is_winner is not None for r in race.official_results.all())
        ):
            reason = 'future_result_state_requires_review'
        if reason:
            held.append({"race_id": race.pk, "reason": reason})
            continue
        classification = classify_result_row(election.election_date, matches[0][0], hints)
        if not classification.resolved:
            held.append({"race_id": race.pk, "reason": ",".join(classification.reasons)})
            continue
        key = event_key(election.election_date, classification)
        targets.setdefault(key, classification.to_dict())
        old_prefix = race.election.canonical_key or f"e{race.election_id}"
        new_key = race.canonical_key
        if new_key:
            if not new_key.startswith(old_prefix + "|"):
                held.append({"race_id": race.pk, "reason": "unrecognized_race_key_prefix"})
                continue
            new_key = key + new_key[len(old_prefix) :]
        moves.append(
            {
                "race_id": race.pk,
                "from_election_id": race.election_id,
                "target_key": key,
                "race_key": new_key,
                "classification": classification.to_dict(),
            }
        )
    seen = {}
    collisions = set()
    for move in moves:
        key = move["race_key"]
        if key and key in seen:
            collisions.update({move["race_id"], seen[key]})
        if key:
            seen[key] = move["race_id"]
            owners = set(
                Race.objects.filter(canonical_key=key).exclude(pk=move["race_id"]).values_list("pk", flat=True)
            )
            if owners:
                collisions.update({move["race_id"], *owners})
    active_ids = {r.pk for r in races if not r.source_metadata.get("nc_superseded_by")}
    already_held = {item["race_id"] for item in held}
    held.extend(
        {"race_id": pk, "reason": "target_key_collision"} for pk in sorted(collisions & active_ids - already_held)
    )
    moves = [move for move in moves if move["race_id"] not in collisions]
    # Only targets with an accepted move are materialized.
    targets = {key: value for key, value in targets.items() if any(m["target_key"] == key for m in moves)}
    # Existing destinations are affected state even when they are not children
    # of this root. Never clear a separate reviewed hold as a side effect.
    destinations = list(Election.objects.filter(canonical_key__in=targets).exclude(pk__in=[e.pk for e in scope])
                        .order_by('pk'))
    blocked = {e.canonical_key for e in destinations if any((e.source_metadata or {}).get(k) for k in
              (CONTAINER, RETIRED, 'nc_classification_held_race_ids'))}
    held.extend({'race_id': m['race_id'], 'reason': 'target_event_held'} for m in moves if m['target_key'] in blocked)
    moves = [m for m in moves if m['target_key'] not in blocked]
    targets = {key:value for key,value in targets.items() if key not in blocked}
    resets = {'race_ids': sorted(m['race_id'] for m in moves) if pre_election else [],
              'reason': 'published_zero_vote_archive_before_election' if pre_election else ''}
    state = {
        "snapshots": [_snapshot(e) for e in scope],
        "destination_snapshots": [_snapshot(e) for e in destinations],
        "destination_source_links": list(ElectionSourceLink.objects.filter(election__in=destinations)
                                         .order_by('pk').values()),
        "source_links": list(ElectionSourceLink.objects.filter(election__in=scope).order_by("pk").values()),
        "source_hashes": source_hashes,
        "filings": filing_rows,
        "results": [dataclasses.asdict(row) for row in result_rows],
        "implementation_code": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("classification.py", "event_identity.py", "election_repair.py")
        },
        "classification_plan": {"targets": targets, "moves": moves, "held": held, 'pre_election_resets': resets},
        "review_day": timezone.localdate().isoformat(),
    }
    return {
        "election_id": election.pk,
        "date": election.election_date.isoformat(),
        "dry_run": True,
        "applied": False,
        "fingerprint": _digest(state),
        "source_hashes": source_hashes,
        "targets": targets,
        "existing_destination_ids": [e.pk for e in destinations],
        "pre_election_resets": resets,
        "moves": moves,
        "held": held,
        "filing_hints": [dict(title=t, party=p, county=c, is_unexpired=v) for (t, p, c), v in sorted(hints.items())],
        "counts": {
            "races": len(races),
            "accepted": len(moves),
            "held": len(held),
            "superseded": sum(bool(r.source_metadata.get("nc_superseded_by")) for r in races),
        },
    }


@transaction.atomic
def apply_classification_plan(election, filing_rows, result_rows, source_hashes, approved, write_report=None):
    if approved.get("election_id") != election.pk or not approved.get("dry_run") or approved.get("applied"):
        raise ClassificationConflict("Approved report must be an unapplied preview for the same election")
    scope = list(_scope(election).select_for_update())
    preview = build_classification_plan(election, filing_rows, result_rows, source_hashes)
    affected = list(Election.objects.select_for_update().filter(
        pk__in={*[e.pk for e in scope], *preview['existing_destination_ids']}).order_by('pk'))
    locked_races = list(Race.objects.select_for_update().filter(election__in=affected))
    races = [r for r in locked_races if r.election_id in {e.pk for e in scope}]
    race_map = {race.pk: race for race in races}
    race_ids = [r.pk for r in locked_races]
    for model, path in (
        (Candidate, "race_id"),
        (MeasureOption, "race_id"),
        (OfficialResult, "race_id"),
        (MockVote, "race_id"),
    ):
        list(model.objects.select_for_update().filter(**{path + "__in": race_ids}).values_list("pk", flat=True))
    list(
        SourceRecord.objects.select_for_update(of=('self',))
        .filter(Q(linked_race_id__in=race_ids) | Q(linked_candidate__race_id__in=race_ids))
        .values_list("pk", flat=True)
    )
    list(ElectionSourceLink.objects.select_for_update().filter(election__in=affected).values_list("pk", flat=True))
    election.refresh_from_db()
    report = build_classification_plan(election, filing_rows, result_rows, source_hashes)
    if report["fingerprint"] != approved.get("fingerprint"):
        raise ClassificationConflict("Source/database fingerprint changed; review a fresh preview")
    target_events = {}
    hint_groups = defaultdict(list)
    for hint in report["filing_hints"]:
        classified = classify_nc_contest(
            election.election_date,
            hint["title"],
            county=hint["county"],
            party_contest=hint["party"],
            is_unexpired=hint["is_unexpired"],
        )
        if classified.resolved:
            hint_groups[event_key(election.election_date, classified)].append(hint)
    # Preserve the original Election ID for a supported one-event rekey.
    if len(report["targets"]) == 1 and not report["held"]:
        key, data = next(iter(report["targets"].items()))
        collision = Election.objects.filter(canonical_key=key).exclude(pk=election.pk).exists()
        if not collision:
            election.canonical_key = key
            election.election_type = data["election_type"]
            election.jurisdiction_level = data["jurisdiction_level"]
            election.source_metadata = {
                **election.source_metadata,
                CLASSIFICATION: event_metadata(NcClassification(**data)),
            }
            election.source_metadata.pop("nc_event_key", None)
            election.save(update_fields=["canonical_key", "election_type", "jurisdiction_level", "source_metadata"])
    for key, data in report["targets"].items():
        classification = NcClassification(**data)
        target = Election.objects.filter(canonical_key=key).first()
        if target is None:
            target, _ = ensure_event(election.election_date, classification)
        combined_hints = {json.dumps(hint, sort_keys=True): hint
                          for hint in [*(target.source_metadata or {}).get('nc_filing_hints', []),
                                       *hint_groups.get(key, [])]}
        metadata = {
            **target.source_metadata,
            CLASSIFICATION: event_metadata(classification),
            "nc_filing_hints": list(combined_hints.values()),
        }
        if target.pk != election.pk and target.pk not in report['existing_destination_ids']:
            metadata["nc_classification_parent_id"] = election.pk
        metadata.pop(CONTAINER, None)
        metadata.pop(RETIRED, None)
        if metadata != target.source_metadata:
            target.source_metadata = metadata
            target.save(update_fields=["source_metadata"])
        target_events[key] = target
    for move in report["moves"]:
        race = race_map[move["race_id"]]
        target = target_events[move["target_key"]]
        metadata = {**race.source_metadata, CLASSIFICATION: move["classification"]}
        changed = (
            race.election_id != target.pk or race.canonical_key != move["race_key"] or race.source_metadata != metadata
        )
        if changed:
            race.election_id = target.pk
            race.canonical_key = move["race_key"]
            race.source_metadata = metadata
            race.save(update_fields=["election", "canonical_key", "source_metadata"])
    reset_ids = report['pre_election_resets']['race_ids']
    if reset_ids:
        pending = election.election_date <= timezone.localdate()
        Race.objects.filter(pk__in=reset_ids).update(certification_status=(
            Race.CertificationStatus.RESULTS_PENDING if pending else Race.CertificationStatus.UPCOMING),
                                                  race_status=Race.RaceStatus.ACTIVE)
        OfficialResult.objects.filter(race_id__in=reset_ids).update(result_type='unofficial', certified_at=None)
        Election.objects.filter(pk__in=[e.pk for e in target_events.values()]).update(
            status=Election.Status.RESULTS_PENDING if pending else Election.Status.UPCOMING)
    held_ids = {item["race_id"] for item in report["held"]}
    replacements = sorted({e.pk for e in target_events.values()} - {election.pk})
    for original in scope:
        original.refresh_from_db()
        metadata = dict(original.source_metadata)
        remaining = Race.objects.filter(election=original).exclude(source_metadata__has_key="nc_superseded_by")
        local_holds = sorted(remaining.filter(pk__in=held_ids).values_list("pk", flat=True))
        metadata["nc_classification_held_race_ids"] = local_holds
        if original.pk == election.pk:
            metadata["nc_classification_replacements"] = replacements
        if original.pk not in {e.pk for e in target_events.values()}:
            metadata[CONTAINER] = bool(local_holds) or not target_events
            metadata[RETIRED] = bool(target_events) and not remaining.exists()
            if metadata[CONTAINER]:
                metadata[CLASSIFICATION] = {"evidence_status": "held", "reasons": ["legacy_identity_components_held"]}
        original.source_metadata = metadata
        if metadata.get(CONTAINER) or metadata.get(RETIRED):
            original.needs_review = True
        original.save(update_fields=["source_metadata", "needs_review"])
    report.update(dry_run=False, applied=True, target_election_ids={k: e.pk for k, e in target_events.items()})
    if write_report:
        write_report(report)
    return report

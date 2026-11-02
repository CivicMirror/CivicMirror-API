"""Read-only NC repair planning and an explicit, fingerprint-checked apply path.

Superseded races/candidates remain as audit tombstones. Their result totals are
retired only after new totals and legitimate relationship mappings are complete.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections import defaultdict

from django.db import transaction
from django.db.models import Q

from aggregation.identity import name_match_key, normalize_party
from community.models import MockVote
from elections.geography import infer_geography_scope
from elections.models import Candidate, Election, MeasureOption, Race
from ops.models import SourceRecord
from results.adapters.base import AdapterResult, ResultRow
from results.models import OfficialResult
from results.nc_identity import IDENTITY_KEY, apply_metadata, contest_party, title_base
from results.tasks import _is_measure_contest, _store_race_results
from results.winners import clear_derived_winners

SUPERSEDED = "nc_superseded_by"


class RepairConflict(ValueError):
    """A repair is stale, ambiguous, or fails vote/relationship conservation."""


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _race_queryset(election):
    return Race.objects.filter(election=election).exclude(source_metadata__has_key=SUPERSEDED).order_by("pk")


def _snapshot(election):
    """Include all mutable evidence and relationships, without publishing private values."""
    race_ids = list(Race.objects.filter(election=election).values_list("pk", flat=True))
    return {
        "election": list(Election.objects.filter(pk=election.pk).values()),
        "races": list(Race.objects.filter(pk__in=race_ids).order_by("pk").values()),
        "candidates": list(Candidate.objects.filter(race_id__in=race_ids).order_by("pk").values()),
        "options": list(MeasureOption.objects.filter(race_id__in=race_ids).order_by("pk").values()),
        "results": list(OfficialResult.objects.filter(race_id__in=race_ids).order_by("pk").values()),
        "votes": list(MockVote.objects.filter(race_id__in=race_ids).order_by("pk").values()),
        "records": list(
            SourceRecord.objects.filter(Q(linked_race_id__in=race_ids) | Q(linked_candidate__race_id__in=race_ids))
            .order_by("pk")
            .values()
        ),
    }


def _row_name(row):
    if row.is_write_in_aggregate:
        return "__write_in__"
    return row.option_label or row.candidate_name or (row.raw or {}).get("choice", "")


def _old_name(result):
    if result.is_write_in_aggregate:
        return "__write_in__"
    if result.candidate_id:
        return result.candidate.name
    if result.measure_option_id:
        return result.measure_option.option_label
    return ""


def _matches(race, rows):
    meta = race.source_metadata or {}
    identity = rows[0].raw[IDENTITY_KEY]
    if meta.get(IDENTITY_KEY):
        return meta[IDENTITY_KEY] == identity
    title = rows[0].office_title
    party = contest_party(title)
    old_party = contest_party(race.office_title) or normalize_party(meta.get("party_contest", "") or race.party)
    if title_base(race.office_title) != title_base(title) or old_party != party:
        return False
    county = str(meta.get("county") or "").upper()
    return not county or county == rows[0].raw.get("county")


def build_repair_plan(election, adapter_result: AdapterResult, race_ids: list[int] | None = None) -> dict:
    """Return mappings, vote reconciliation, blockers and a reproducible fingerprint; no writes."""
    if election.state != "NC":
        raise RepairConflict("Only NC elections may be repaired")
    if not adapter_result.rows or adapter_result.unchanged or adapter_result.mapping_confidence != "full":
        raise RepairConflict("A complete, freshly fetched NC source is required")
    source = defaultdict(list)
    for row in adapter_result.rows:
        if not (row.raw or {}).get(IDENTITY_KEY):
            raise RepairConflict("Every source row must carry NC contest identity")
        source[row.raw[IDENTITY_KEY]].append(row)
    races = list(
        _race_queryset(election).prefetch_related(
            "candidates", "measure_options", "official_results__candidate", "official_results__measure_option"
        )
    )
    candidates = {c.pk: c for race in races for c in race.candidates.all()}
    race_map = {str(race.pk): [key for key, rows in source.items() if _matches(race, rows)] for race in races}
    if race_ids is not None:
        all_races = {race.pk: race for race in Race.objects.filter(election=election)}
        selected, visited, pending = set(), set(), list(race_ids)
        while pending:
            pk = pending.pop()
            if pk in visited:
                continue
            visited.add(pk)
            prior = all_races.get(pk)
            if prior is None:
                raise RepairConflict("Scope must name existing races in this NC election")
            replacements = (prior.source_metadata or {}).get(SUPERSEDED)
            if replacements:
                pending.extend(replacements)
            else:
                selected.add(pk)
        if not selected:
            raise RepairConflict("Scope has no canonical races; inspect retirement links")
        keys = set()
        while True:
            keys.update(key for pk in selected for key in race_map[str(pk)])
            expanded = {r.pk for r in races if set(race_map[str(r.pk)]) & keys} | selected
            if expanded == selected:
                break
            selected = expanded
        races = [race for race in races if race.pk in selected]
        race_map = {str(race.pk): race_map[str(race.pk)] for race in races}
        source = {key: rows for key, rows in source.items() if key in keys}
        candidates = {c.pk: c for race in races for c in race.candidates.all()}
    groups, conflicts, reconciliation = [], [], []
    candidate_map, option_map = {}, {}

    def conflict(reason, **details):
        conflicts.append({"reason": reason, **details})

    for key, rows in sorted(source.items()):
        members = [race for race in races if key in race_map[str(race.pk)]]
        single = [race for race in members if len(race_map[str(race.pk)]) == 1]
        labels = [_row_name(row) for row in rows if not row.is_write_in_aggregate]
        measure = _is_measure_contest(rows[0].office_title, labels)
        expected_type = Race.RaceType.MEASURE if measure else Race.RaceType.CANDIDATE
        canonical = min(
            (r for r in single if r.race_type == expected_type),
            key=lambda race: (race.source != Race.Source.NC_SBE, race.pk),
            default=None,
        )
        group = {
            "identity": key,
            "office_title": rows[0].office_title,
            "race_type": Race.RaceType.MEASURE if measure else Race.RaceType.CANDIDATE,
            "existing_race_ids": [race.pk for race in members],
            "canonical_race_id": canonical.pk if canonical else None,
            "new_total": sum(row.vote_count for row in rows),
            "source_winners": {},
            "rows": [dataclasses.asdict(row) for row in rows],
        }
        groups.append(group)
        if not all(row.raw.get("nc_identity_verified") for row in rows):
            conflict("unresolved_electorate", identity=key)
        if any(row.raw.get("nc_vote_errors") for row in rows):
            conflict("invalid_source_votes", identity=key)
        names = [name_match_key(_row_name(row)) for row in rows]
        if len(names) != len(set(names)):
            conflict("ambiguous_source_choice_names", identity=key)
        for race in members:
            if race.source not in {Race.Source.NC_SBE, Race.Source.RESULTS_ADAPTER}:
                conflict("unreviewed_race_source", race_id=race.pk, identity=key)
        for row in rows:
            name = name_match_key(_row_name(row))
            if row.is_write_in_aggregate:
                continue
            matching = [c for race in members for c in race.candidates.all() if name_match_key(c.name) == name]
            if not measure:
                parties = {normalize_party(c.party) for c in matching if c.party}
                parties |= {normalize_party(c.normalized_party) for c in matching if c.normalized_party}
                parties |= {row.raw.get("party", "")} - {""}
                parties |= set(row.raw.get("party_conflict", [])) - {""}
                if len(parties) > 1:
                    conflict("candidate_party_conflict", identity=key, name=_row_name(row), parties=sorted(parties))
                for field in ("fec_candidate_id", "bioguide_id", "openstates_person_id", "ocpf_filer_id"):
                    if len({getattr(c, field) for c in matching if getattr(c, field)}) > 1:
                        conflict("candidate_identifier_conflict", identity=key, name=_row_name(row), field=field)
                explicit = {c.incumbent for c in matching if (c.field_provenance or {}).get("incumbent")}
                if len(explicit) > 1:
                    conflict("candidate_incumbency_conflict", identity=key, name=_row_name(row))
            for candidate in matching:
                candidate_map.setdefault(str(candidate.pk), []).append({"identity": key, "name": _row_name(row)})
            for option in [
                o for race in members for o in race.measure_options.all() if name_match_key(o.option_label) == name
            ]:
                option_map.setdefault(str(option.pk), []).append({"identity": key, "name": _row_name(row)})

    groups_by_key = {group["identity"]: group for group in groups}
    for race in races:
        destinations = race_map[str(race.pk)]
        if not destinations:
            conflict("race_missing_from_source", race_id=race.pk, office_title=race.office_title)
            continue
        for candidate in race.candidates.all():
            if str(candidate.pk) not in candidate_map:
                conflict("candidate_missing_from_source", race_id=race.pk, candidate_id=candidate.pk)
        for option in race.measure_options.all():
            if str(option.pk) not in option_map:
                conflict("option_missing_from_source", race_id=race.pk, option_id=option.pk)
        seen_slots = set()
        for old in race.official_results.all():
            name = name_match_key(_old_name(old))
            targets = [
                (key, row) for key in destinations for row in source[key] if name_match_key(_row_name(row)) == name
            ]
            total = sum(row.vote_count for _, row in targets)
            matched = (
                bool(targets)
                and old.vote_count == total
                and old.round_number is None
                and old.jurisdiction_fragment == ""
            )
            correction = None
            if (
                not matched
                and old.is_write_in_aggregate
                and targets
                and old.round_number is None
                and not old.jurisdiction_fragment
                and (old.raw_payload or {}).get("source") == "nc_sbe"
            ):
                components = [value for _, row in targets for value in row.raw.get("write_in_components", {}).values()]
                if (
                    len(components) > 1
                    and old.vote_count in components
                    and sum(components) == total
                    and old.vote_count <= total
                ):
                    matched = True
                    correction = "write_in_reaggregation"
            reconciliation.append(
                {
                    "old_result_id": old.pk,
                    "old_race_id": race.pk,
                    "old_votes": old.vote_count,
                    "new_votes": total,
                    "new_identities": sorted({key for key, _ in targets}),
                    "matched": matched,
                    "correction": correction,
                }
            )
            if not matched:
                conflict("vote_mismatch", old_result_id=old.pk, old_votes=old.vote_count, new_votes=total)
            slot = (name, old.round_number, old.jurisdiction_fragment)
            if slot in seen_slots:
                conflict("duplicate_legacy_result_slot", race_id=race.pk, name=name)
            seen_slots.add(slot)
            if old.is_winner is not None and not (race.source_metadata or {}).get("winners_derived"):
                if len(targets) != 1:
                    conflict("ambiguous_source_winner_split", old_result_id=old.pk)
                else:
                    group = groups_by_key[targets[0][0]]
                    prior = group["source_winners"].get(name)
                    if prior is not None and prior != old.is_winner:
                        conflict("conflicting_source_winners", identity=group["identity"], name=name)
                    group["source_winners"][name] = old.is_winner

    # A split candidate may legitimately appear in more than one county; only
    # relationships that cannot choose one destination block application.
    for record in SourceRecord.objects.filter(
        Q(linked_race_id__in=[r.pk for r in races]) | Q(linked_candidate_id__in=candidates)
    ):
        targets = (
            candidate_map.get(str(record.linked_candidate_id), [])
            if record.linked_candidate_id
            else [{"identity": key} for key in race_map.get(str(record.linked_race_id), [])]
        )
        if len(targets) != 1 or (
            record.linked_candidate_id and targets and groups_by_key[targets[0]["identity"]]["race_type"] != "candidate"
        ):
            conflict("ambiguous_source_record_relationship", source_record_id=record.pk)
    vote_targets = set()
    for vote in MockVote.objects.filter(race_id__in=[r.pk for r in races]).order_by("pk"):
        selections = (vote.candidate_ids or []) + (vote.ranked_selections or [])
        mappings = [candidate_map.get(str(pk), []) for pk in selections]
        if vote.measure_option_id:
            mappings.append(option_map.get(str(vote.measure_option_id), []))
        targets = {m[0]["identity"] for m in mappings if len(m) == 1}
        if (
            not mappings
            or any(len(m) != 1 for m in mappings)
            or len(targets) != 1
            or (selections and any(groups_by_key[key]["race_type"] != "candidate" for key in targets))
        ):
            conflict("ambiguous_mock_vote_relationship", mock_vote_id=vote.pk)
        else:
            target = (vote.uid, next(iter(targets)))
            if target in vote_targets:
                conflict("duplicate_mock_vote_relationship", mock_vote_id=vote.pk)
            vote_targets.add(target)
    report = {
        "scope_race_ids": sorted(race_ids) if race_ids is not None else None,
        "election_id": election.pk,
        "election_date": str(election.election_date),
        "source_url": adapter_result.source_url,
        "source_version": adapter_result.source_version,
        "dry_run": True,
        "applied": False,
        "groups": groups,
        "race_mapping": race_map,
        "candidate_mapping": candidate_map,
        "option_mapping": option_map,
        "vote_reconciliation": reconciliation,
        "conflicts": conflicts,
        "inventory": {
            "existing_races": len(races),
            "source_contests": len(groups),
            "merged_races": sum(
                len(keys) > 1
                and all(
                    all(row["raw"].get("nc_identity_verified") for row in groups_by_key[key]["rows"]) for key in keys
                )
                for keys in race_map.values()
            ),
            "unresolved_race_splits": sum(
                len(keys) > 1
                and any(
                    not all(row["raw"].get("nc_identity_verified") for row in groups_by_key[key]["rows"])
                    for key in keys
                )
                for keys in race_map.values()
            ),
            "duplicate_groups": sum(len(g["existing_race_ids"]) > 1 for g in groups),
        },
    }
    report["fingerprint"] = _digest({"report": report, "database": _snapshot(election)})
    return report


def _merge_candidate(target, others):
    """Fill absent detail; leave contradictory authoritative evidence to the planner."""
    explicit_incumbency = {c.incumbent for c in [target, *others] if c.field_provenance.get("incumbent")}
    for source in others:
        if source.pk == target.pk:
            continue
        for field in (
            "party",
            "normalized_party",
            "description",
            "image_url",
            "website_url",
            "fec_candidate_id",
            "bioguide_id",
            "openstates_person_id",
            "ocpf_filer_id",
            "contact_phone",
            "contact_office",
        ):
            if not getattr(target, field) and getattr(source, field):
                setattr(target, field, getattr(source, field))
        if source.incumbent and not target.field_provenance.get("incumbent"):
            target.incumbent = True
        target.field_provenance = {**source.field_provenance, **target.field_provenance}
        target.contributing_sources = sorted(set(target.contributing_sources) | set(source.contributing_sources))
        meta = dict(target.source_metadata or {})
        meta.setdefault("nc_merged_candidate_metadata", {})[str(source.pk)] = source.source_metadata
        target.source_metadata = meta
    if len(explicit_incumbency) == 1:
        target.incumbent = next(iter(explicit_incumbency))
    target.normalized_party = normalize_party(target.party)
    target.save()


def _already_current(race, rows, source_url):
    if not race.source_metadata.get(IDENTITY_KEY) or race.certification_status != "results_certified":
        return False
    stored = list(race.official_results.select_related("candidate", "measure_option"))
    if len(stored) != len(rows):
        return False
    by_name = {name_match_key(_old_name(row)): row for row in stored}
    for row in rows:
        old = by_name.get(name_match_key(_row_name(row)))
        if (
            old is None
            or old.vote_count != row.vote_count
            or old.raw_payload != row.raw
            or old.source_url != source_url
            or old.result_type != row.result_type
            or old.jurisdiction_fragment
            or old.round_number is not None
        ):
            return False
        if (
            old.candidate_id
            and row.raw.get("party")
            and (not old.candidate.party or not old.candidate.normalized_party)
        ):
            return False
    return True


@transaction.atomic
def apply_repair_plan(
    election, adapter_result: AdapterResult, expected_fingerprint: str, race_ids: list[int] | None = None
) -> dict:
    """Lock, re-plan and apply exactly the reviewed source/database snapshot, or roll back."""
    election = Election.objects.select_for_update().get(pk=election.pk)
    # Ingestion takes race locks; consistent PK order prevents competing repair deadlocks.
    list(Race.objects.select_for_update().filter(election=election).order_by("pk"))
    report = build_repair_plan(election, adapter_result, race_ids=race_ids)
    if report["fingerprint"] != expected_fingerprint:
        raise RepairConflict("Source or database changed since the reviewed report; run dry-run again")
    if report["conflicts"]:
        raise RepairConflict(f"Repair has {len(report['conflicts'])} unresolved conflicts; no changes applied")
    old_races = {race.pk: race for race in _race_queryset(election) if str(race.pk) in report["race_mapping"]}
    old_candidates = {c.pk: c for c in Candidate.objects.filter(race__in=old_races)}
    target_races, target_candidates, target_options = {}, {}, {}
    for group in report["groups"]:
        key = group["identity"]
        rows = [ResultRow(**row) for row in group["rows"]]
        race = old_races.get(group["canonical_race_id"])
        if race is None:
            race = Race.objects.create(
                election=election,
                office_title=group["office_title"],
                race_type=group["race_type"],
                source=Race.Source.RESULTS_ADAPTER,
                jurisdiction=rows[0].raw.get("county") or "NC",
                geography_scope=infer_geography_scope(group["office_title"]),
            )
        target_races[key] = race
        if group["existing_race_ids"] == [race.pk] and _already_current(race, rows, adapter_result.source_url):
            for row in rows:
                name = _row_name(row)
                if row.is_write_in_aggregate:
                    continue
                if group["race_type"] == Race.RaceType.MEASURE:
                    target_options[(key, name)] = next(
                        o for o in race.measure_options.all() if name_match_key(o.option_label) == name_match_key(name)
                    )
                else:
                    target_candidates[(key, name)] = next(
                        c for c in race.candidates.all() if name_match_key(c.name) == name_match_key(name)
                    )
            continue
        clear_derived_winners(race)
        for row in rows:
            if row.is_write_in_aggregate:
                continue
            name = _row_name(row)
            match_key = name_match_key(name)
            if group["race_type"] == Race.RaceType.MEASURE:
                option = next(
                    (o for o in race.measure_options.all() if name_match_key(o.option_label) == match_key), None
                )
                option = option or MeasureOption.objects.create(race=race, option_label=name)
                target_options[(key, name)] = option
            else:
                others = [
                    old_candidates[int(pk)]
                    for pk, choices in report["candidate_mapping"].items()
                    if {"identity": key, "name": name} in choices
                ]
                candidate = next((c for c in race.candidates.all() if name_match_key(c.name) == match_key), None)
                candidate = candidate or Candidate.objects.create(race=race, name=name)
                _merge_candidate(candidate, others)
                target_candidates[(key, name)] = candidate
                # Match the stored canonical name without loosening generic ingestion.
                row.candidate_name = candidate.name
            source_flag = group["source_winners"].get(match_key)
            if source_flag is not None:
                row.is_winner = source_flag
        apply_metadata(race, rows, adapter_result.source_url)
        members = [old_races[pk] for pk in group["existing_race_ids"]]
        sources = set(race.contributing_sources)
        links = list(race.source_links)
        metadata = dict(race.source_metadata)
        metadata["nc_merged_race_metadata"] = {str(r.pk): r.source_metadata for r in members if r.pk != race.pk}
        for old in members:
            sources.add(old.source)
            sources.update(old.contributing_sources)
            for link in old.source_links:
                if link not in links:
                    links.append(link)
        race.contributing_sources, race.source_links, race.source_metadata = sorted(sources), links, metadata
        race.save(update_fields=["contributing_sources", "source_links", "source_metadata"])
        # Only delete this slot set after the whole plan has reconciled it.
        # Preserve source flags supplied by a canonical repeat run as well.
        flags = {
            name_match_key(_old_name(r)): r.is_winner
            for r in race.official_results.select_related("candidate", "measure_option")
            if r.is_winner is not None
        }
        for row in rows:
            if row.is_winner is None and name_match_key(_row_name(row)) in flags:
                row.is_winner = flags[name_match_key(_row_name(row))]
        race.official_results.all().delete()
        _store_race_results(race, dataclasses.replace(adapter_result, rows=rows), "NC")

    def candidate_target(pk):
        choices = report["candidate_mapping"][str(pk)]
        item = choices[0]
        return target_candidates[(item["identity"], item["name"])]

    for record in SourceRecord.objects.filter(
        Q(linked_race_id__in=old_races) | Q(linked_candidate_id__in=old_candidates)
    ):
        if record.linked_candidate_id:
            candidate = candidate_target(record.linked_candidate_id)
            record.linked_candidate = candidate
            if record.linked_race_id:
                record.linked_race = candidate.race
        elif record.linked_race_id:
            record.linked_race = target_races[report["race_mapping"][str(record.linked_race_id)][0]]
        record.save(update_fields=["linked_race", "linked_candidate"])
    for vote in MockVote.objects.filter(race_id__in=old_races):
        target = None
        for field in ("candidate_ids", "ranked_selections"):
            if getattr(vote, field):
                remapped = [candidate_target(pk) for pk in getattr(vote, field)]
                setattr(vote, field, [c.pk for c in remapped])
                target = remapped[0].race
        if vote.measure_option_id:
            item = report["option_mapping"][str(vote.measure_option_id)][0]
            option = target_options[(item["identity"], item["name"])]
            vote.measure_option_id, target = option.pk, option.race
        vote.race = target
        vote.save(update_fields=["race", "candidate_ids", "ranked_selections", "measure_option_id"])
    canonical_ids = {race.pk for race in target_races.values()}
    for old in old_races.values():
        if old.pk in canonical_ids:
            continue
        targets = [target_races[key].pk for key in report["race_mapping"][str(old.pk)]]
        old.official_results.all().delete()
        meta = dict(old.source_metadata or {})
        meta.pop("winners_derived", None)
        meta[SUPERSEDED] = targets
        old.source_metadata = meta
        old.race_status = Race.RaceStatus.CANCELLED
        old.certification_status = Race.CertificationStatus.PARTIAL_RESULTS
        old.canonical_key = None
        old.save(update_fields=["source_metadata", "race_status", "certification_status", "canonical_key"])
    report["applied"] = True
    report["dry_run"] = False
    report["canonical_race_ids"] = {key: race.pk for key, race in target_races.items()}
    return report

"""Conservative, source-specific party plans shared by bootstrap and backfill."""
import re

from aggregation.identity import normalize_party

SUPPORTED_STATES = {"CT", "GA", "MO", "PA"}
UNRESOLVED_KEY = "results_party_unresolved"
_GA_SUFFIX = re.compile(r"\s+-\s+(Dem|Rep|GOP|Lib|Grn|Ind|NP)$", re.I)


def _codes(values):
    return {normalize_party(str(value)) for value in values if value and str(value).strip()}


def plan_party_updates(race, candidates, rows, source_url=""):
    """Plan missing-field writes only. No result counts, identities or flags are changed."""
    state = race.election.state
    plan = {"race_id": race.pk, "state": state, "changes": [], "unresolved": []}
    if state not in SUPPORTED_STATES or race.source != "results_adapter" or race.race_type != "candidate":
        return plan
    candidates = list(candidates)
    rows = list(rows)
    meta = dict(race.source_metadata or {})
    primary = race.election.election_type in {"primary", "primary_runoff"}
    specific = []
    if primary and state == "CT" and meta.get("contest_code"):
        specific.append(meta.get("party_code"))
    if primary and state == "GA":
        suffix = _GA_SUFFIX.search(race.office_title)
        if suffix:
            specific.append(suffix.group(1))
    race_codes = _codes([race.party, race.normalized_party, *specific])

    # MO's historical adapter cannot substantiate a 2026 primary with its fixed 2024 general PDF.
    mismatch = state == "MO" and (
        str(race.election.election_date) != "2024-11-05" or race.election.election_type != "general"
    )

    def assignment(obj, kind, evidence):
        codes = _codes([obj.party, obj.normalized_party, *evidence])
        if len(codes) != 1:
            plan["unresolved"].append({
                "model": kind, "id": obj.pk,
                "reason": "conflicting_party" if codes else "missing_party", "evidence": sorted(codes),
            })
            return
        code = next(iter(codes))
        fields = {key: code for key in ("party", "normalized_party") if not getattr(obj, key)}
        if fields:
            provenance = dict(obj.field_provenance or {})
            for key in fields:
                provenance.setdefault(key, f"results_adapter:{state}:party_metadata")
            fields["field_provenance"] = provenance
            plan["changes"].append({"model": kind, "id": obj.pk, "fields": fields, "evidence": sorted(codes)})

    if mismatch:
        plan["unresolved"].append({"model": "race", "id": race.pk, "reason": "source_election_mismatch"})
    else:
        if race_codes or specific:
            assignment(race, "race", specific)
        for candidate in candidates:
            evidence = list(race_codes)
            for row in rows:
                name = getattr(row, "candidate_name", None)
                if name is None:
                    if getattr(row, "candidate_id", None) != candidate.pk:
                        continue
                elif name.strip() != candidate.name:
                    continue
                raw = getattr(row, "raw", None) or getattr(row, "raw_payload", None) or {}
                evidence.append(raw.get("party_code") if state == "CT" else raw.get("party"))
                evidence.extend(raw.get("party_conflict", []))
            assignment(candidate, "candidate", evidence)

    # A known race party must not hide conflicting candidate evidence from winner derivation.
    if plan["unresolved"]:
        meta[UNRESOLVED_KEY] = plan["unresolved"]
    else:
        meta.pop(UNRESOLVED_KEY, None)
    if meta != (race.source_metadata or {}):
        plan["changes"].append({"model": "race", "id": race.pk, "fields": {"source_metadata": meta}})
    return plan


def apply_party_plan(race, candidates, plan):
    """Apply under the caller's race lock (or serialized bootstrap transaction)."""
    by_id = {candidate.pk: candidate for candidate in candidates}
    for change in plan["changes"]:
        obj = race if change["model"] == "race" else by_id[change["id"]]
        for key, value in change["fields"].items():
            setattr(obj, key, value)
        obj.save(update_fields=list(change["fields"]))

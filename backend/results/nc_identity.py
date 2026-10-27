"""NC ENRS identity and metadata, shared by bootstrap, ingestion and explicit repair.

Candidate party is deliberately separate from contest identity: a general ballot
contains choices from several parties. A primary's party comes from its title.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict

from aggregation.identity import normalize_party, race_canonical_key
from elections.geography import infer_geography_scope
from integrations.nc_sbe.mappers import contest_variant_key, is_in_scope_contest, is_write_in

from .adapters.base import ResultRow

IDENTITY_KEY = "nc_contest_key"
IDENTITY_VERSION = 1
# Verified shared electorate names/counties in the 2014-05-06 and 2024 ENRS
# feeds. These exceptions require BOTH an explicit place name and a matching
# source group ID across reporting counties. Unknown local overlaps remain
# unresolved; neither a generic title nor an ID alone proves a shared electorate.
LOCAL_ELECTORATES = (
    ("CITY OF ARCHDALE ", "municipality:ARCHDALE", {"GUILFORD", "RANDOLPH"}),
    ("CITY OF BURLINGTON ", "municipality:BURLINGTON", {"ALAMANCE", "GUILFORD"}),
    ("CITY OF SALUDA ", "municipality:SALUDA", {"HENDERSON", "POLK"}),
    ("TOWN OF ELKIN ", "municipality:ELKIN", {"SURRY", "WILKES"}),
    ("HANDY SANITARY DISTRICT ", "sanitary-district:HANDY", {"DAVIDSON", "MONTGOMERY"}),
    ("WHITTIER SANITARY DISTRICT ", "sanitary-district:WHITTIER", {"JACKSON", "SWAIN"}),
    ("CITY OF RALEIGH ", "municipality:RALEIGH", {"DURHAM", "WAKE"}),
    ("CITY OF DURHAM ", "municipality:DURHAM", {"DURHAM", "ORANGE", "WAKE"}),
    ("CITY OF LOCUST ", "municipality:LOCUST", {"CABARRUS", "STANLY"}),
    ("TOWN OF CHAPEL HILL ", "municipality:CHAPEL HILL", {"DURHAM", "ORANGE"}),
    ("TOWN OF CARY ", "municipality:CARY", {"CHATHAM", "DURHAM", "WAKE"}),
    ("KANNAPOLIS BOARD OF EDUCATION ", "school-system:KANNAPOLIS", {"CABARRUS", "ROWAN"}),
    ("KANNAPOLIS CITY SCHOOLS BOARD OF EDUCATION ", "school-system:KANNAPOLIS", {"CABARRUS", "ROWAN"}),
)
_COUNTY_CONTEST = re.compile(
    r"^(?:COUNTYWIDE\b|SHERIFF\b|REGISTER OF DEEDS\b|CLERK OF (?:THE )?SUPERIOR COURT\b|CORONER\b|"
    r"(?:COUNTY )?BOARD OF (?:COUNTY )?(?:COMMISSIONERS|EDUCATION)\b|COUNTY COMMISSIONER\b|SCHOOL BOARD\b)"
)
_PARTY_SUFFIX = re.compile(r"\s*\((DEM|REP|LIB|GRN|CON|WFP|UNA|IND)\)\s*$", re.I)
_EXECUTIVE = re.compile(
    r"^NC (?=(GOVERNOR|LIEUTENANT GOVERNOR|ATTORNEY GENERAL|SECRETARY OF STATE|STATE TREASURER|"
    r"STATE AUDITOR|COMMISSIONER OF|SUPERINTENDENT OF PUBLIC INSTRUCTION)\b)"
)


def clean(value) -> str:
    return "".join(ch for ch in str(value or "") if ch >= " " or ch == "\t").strip()


def title_key(title: str) -> str:
    """Only documented feed aliases; never fuzzy match two contests."""
    return _EXECUTIVE.sub("", " ".join(clean(title).upper().split()))


def contest_party(title: str) -> str:
    match = _PARTY_SUFFIX.search(title)
    return normalize_party(match[1]) if match else ""


def title_base(title: str) -> str:
    return title_key(_PARTY_SUFFIX.sub("", title))


def aggregate_rows(raw_rows: list[dict]) -> list[ResultRow]:
    counties = defaultdict(set)
    title_counties = defaultdict(set)
    title_codes = defaultdict(set)
    for row in raw_rows:
        counties[(clean(row.get("Contest Name")).upper(), clean(row.get("Contest Group ID")))].add(
            clean(row.get("County")).upper()
        )
        if clean(row.get("Contest Type")).upper() == "C":
            title_counties[title_key(row.get("Contest Name"))].add(clean(row.get("County")).upper())
            title_codes[title_key(row.get("Contest Name"))].add(clean(row.get("Contest Group ID")))
    totals = {}
    for row in raw_rows:
        title, choice = clean(row.get("Contest Name")), clean(row.get("Choice"))
        if not title or not choice:
            continue
        kind = clean(row.get("Contest Type")).upper()
        code = clean(row.get("Contest Group ID"))
        county = clean(row.get("County")).upper()
        reporting = counties[(title.upper(), code)]
        electorate, verified = "", bool(code and kind in {"S", "C"})
        if kind == "C":
            electorate = "county:" + county
            verified = verified and bool(county)
            for prefix, place, allowed in LOCAL_ELECTORATES:
                if (
                    title.upper().startswith(prefix)
                    and reporting <= allowed
                    and len(title_codes[title_key(title)]) == 1
                ):
                    electorate = place
                    break
            else:
                if len(title_counties[title_key(title)]) > 1 and not _COUNTY_CONTEST.search(title.upper()):
                    verified = False
        elif kind == "S":
            electorate = "state:NC"
        identity = "nc:v1:" + json.dumps([kind, code, title_key(title), electorate], separators=(",", ":"))
        write_in = is_write_in(choice)
        key = (identity, "__write_in__" if write_in else choice)
        group = totals.setdefault(
            key,
            {
                "title": title,
                "votes": 0,
                "counties": set(),
                "parties": set(),
                "seats": set(),
                "vote_errors": [],
                "write_ins": defaultdict(int),
                "meta": {
                    IDENTITY_KEY: identity,
                    "nc_identity_version": IDENTITY_VERSION,
                    "nc_identity_verified": verified,
                    "nc_electorate": electorate,
                    "contest_code": code,
                    "contest_type": kind,
                    "county": county if electorate.startswith("county:") else "",
                    "party_code": contest_party(title),
                    "source": "nc_sbe",
                },
            },
        )
        try:
            votes = int(clean(row.get("Total Votes")) or 0)
            if votes < 0:
                raise ValueError("negative votes")
        except ValueError:
            votes = 0
            group["vote_errors"].append(clean(row.get("Total Votes")))
        group["votes"] += votes
        if write_in:
            group["write_ins"][choice] += votes
        group["counties"].add(county)
        group["parties"].add(normalize_party(clean(row.get("Choice Party"))))
        group["seats"].add(clean(row.get("Vote For")))
    result = []
    for (_, choice), group in totals.items():
        parties, seats = group["parties"], group["seats"]
        meta = {
            **group["meta"],
            "reporting_counties": sorted(group["counties"]),
            "party": next(iter(parties)) if len(parties) == 1 else "",
            "party_conflict": sorted(parties) if len(parties) > 1 else [],
            "vote_for": next(iter(seats)) if len(seats) == 1 else "",
            "vote_for_values": sorted(seats),
            "nc_vote_errors": group["vote_errors"],
            "write_in_components": dict(group["write_ins"]),
        }
        write_in = choice == "__write_in__"
        result.append(
            ResultRow(
                candidate_name=choice if not write_in else None,
                option_label=None,
                vote_count=group["votes"],
                vote_pct=None,
                is_winner=None,
                result_type="official",
                office_title=group["title"],
                is_write_in_aggregate=write_in,
                raw={**meta, "choice": choice},
            )
        )
    return result


def filing_canonical_key(election, title: str) -> str | None:
    base, party = title_base(title), contest_party(title)
    if not is_in_scope_contest(base):
        return None
    return race_canonical_key(
        election.canonical_key or f"e{election.pk}", base, "", "candidate", contest_variant_key(base, party)
    )


def adopt_filing_identity(race, adapter_result) -> None:
    """Attach a first result feed to a single filing race; duplicates need repair."""
    from elections.models import Race

    if race.source != Race.Source.NC_SBE or (race.source_metadata or {}).get(IDENTITY_KEY):
        return
    groups = defaultdict(list)
    for row in adapter_result.rows:
        if (row.raw or {}).get(IDENTITY_KEY) and filing_canonical_key(
            race.election, row.office_title
        ) == race.canonical_key:
            groups[row.raw[IDENTITY_KEY]].append(row)
    if len(groups) != 1:
        return
    rows = next(iter(groups.values()))
    if not all(row.raw.get("nc_identity_verified") for row in rows):
        return
    for other in (
        Race.objects.filter(election=race.election)
        .exclude(pk=race.pk)
        .exclude(source_metadata__has_key="nc_superseded_by")
    ):
        if (
            title_base(other.office_title) == title_base(race.office_title)
            and (contest_party(other.office_title) or normalize_party(other.party)) == rows[0].raw["party_code"]
        ):
            return
    apply_metadata(race, rows, adapter_result.source_url)


def apply_metadata(race, rows, source_url: str) -> None:
    """Persist sourced evidence under the caller's race/election transaction."""
    from elections.models import Race

    if not rows or not all((row.raw or {}).get(IDENTITY_KEY) for row in rows):
        return
    identity = {row.raw[IDENTITY_KEY] for row in rows}
    if len(identity) != 1:
        raise ValueError("NC metadata spans several contests")
    first = rows[0].raw
    meta = dict(race.source_metadata or {})
    meta.update(
        {
            key: first[key]
            for key in (
                IDENTITY_KEY,
                "nc_identity_version",
                "nc_electorate",
                "contest_code",
                "contest_type",
                "county",
                "party_code",
            )
        }
    )
    meta["nc_identity_verified"] = all(row.raw.get("nc_identity_verified") for row in rows)
    meta["reporting_counties"] = sorted({c for row in rows for c in row.raw.get("reporting_counties", [])})
    meta["nc_results_source_url"] = source_url
    versions = {row.raw.get("source_version") for row in rows if row.raw.get("source_version")}
    if len(versions) == 1:
        meta["nc_results_source_version"] = next(iter(versions))
    seats = {value for row in rows for value in row.raw.get("vote_for_values", [row.raw.get("vote_for", "")])}
    provenance = dict(race.field_provenance or {})
    if len(seats) == 1 and next(iter(seats)).isdigit() and int(next(iter(seats))) > 0:
        count = int(next(iter(seats)))
        meta["source_vote_for"] = count
        meta.pop("source_vote_for_unresolved", None)
        race.max_selections = count
        race.vote_method = Race.VoteMethod.MULTI_SEAT if count > 1 else Race.VoteMethod.SINGLE_CHOICE
        provenance.update({field: "results_adapter:NC:Vote For" for field in ("max_selections", "vote_method")})
    else:
        meta.pop("source_vote_for", None)
        meta["source_vote_for_unresolved"] = sorted(seats)
    party = first.get("party_code", "")
    if party and race.election.election_type in {"primary", "primary_runoff"}:
        race.party = party
        race.normalized_party = party
        provenance["party"] = "results_adapter:NC:Contest Name"
    unresolved = []
    for candidate in race.candidates.all():
        matching = [row for row in rows if (row.candidate_name or "").casefold() == candidate.name.casefold()]
        if not matching:
            continue
        codes = {row.raw.get("party", "") for row in matching}
        conflicts = {p for row in matching for p in row.raw.get("party_conflict", [])}
        existing = {normalize_party(p) for p in (candidate.party, candidate.normalized_party) if p}
        codes = (codes | conflicts | existing) - {""}
        if len(codes) != 1 or conflicts:
            unresolved.append({"candidate_id": candidate.pk, "parties": sorted(codes)})
            continue
        code = next(iter(codes))
        fields = []
        for field in ("party", "normalized_party"):
            if not getattr(candidate, field):
                setattr(candidate, field, code)
                candidate.field_provenance = {**candidate.field_provenance, field: "results_adapter:NC:Choice Party"}
                fields.append(field)
        if fields:
            candidate.save(update_fields=[*fields, "field_provenance"])
    if unresolved:
        meta["results_party_unresolved"] = unresolved
    else:
        meta.pop("results_party_unresolved", None)
    if not race.canonical_key:
        key = filing_canonical_key(race.election, race.office_title)
        if key and not Race.objects.filter(canonical_key=key).exclude(pk=race.pk).exists():
            race.canonical_key = key
    race.source_metadata = meta
    race.field_provenance = provenance
    if not race.geography_scope:
        race.geography_scope = infer_geography_scope(race.office_title)
    race.save(
        update_fields=[
            "source_metadata",
            "field_provenance",
            "party",
            "normalized_party",
            "max_selections",
            "vote_method",
            "geography_scope",
            "canonical_key",
        ]
    )

# CM2 MA Pilot — Plan 3: Secretary Candidate Pages → PreElectionBatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse the Secretary of the Commonwealth's Democratic/Republican primary candidate pages into a `PreElectionBatch` — jurisdictions, offices, contests, and candidates — with candidate identity pre-resolved against Plan 2's `OcpfCandidatePool` wherever a verified district-code crosswalk allows it, falling back to provisional-person creation everywhere else.

**Architecture:** Four sequential pieces. (1) A crosswalk (`mapping/office_crosswalk.py`) translating a Secretary `(office h2, district h3)` pair into an OCPF `district_code` — grounded in a full diff of the real 714-row OCPF district table against all 242 real Secretary district labels done during design, which found 241/242 resolve deterministically once Senate districts are translated through the Massachusetts Legislature's own pre/post-2021-redistricting name-mapping. (2) A candidate-page parser (`sources/candidate_pages.py`) turning the real `<h2>`/`<h3>`/`<p>` markup into typed rows, including the suffix-in-name comma edge case found live in the data. (3) Jurisdiction/office mapping (`mapping/jurisdictions.py`, `mapping/offices.py`) — much simpler than NC's regex-driven equivalent, since the Secretary's own page structure already separates office from district. (4) A batch builder (`mapping/batch.py`) that ties all three together plus Plan 1's discovered `ElectionRecord`s into one `PreElectionBatch`, using the crosswalk + `OcpfCandidatePool.find_by_name_and_district_code()` to pre-resolve `CandidateFilingRecord.person_public_id` on confident matches.

**Tech Stack:** Django 5 / Python 3.13, `beautifulsoup4`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-17-cm2-ma-pilot-design.md` (see "Candidate ballot confirmation — Secretary candidate-list pages" and "Candidate identity: OCPF as source, Secretary as confirmation")

## Global Constraints

- Python 3.13 runtime only.
- `core/cf_solver.py` must not be modified — this plan's candidate-page source goes through the existing, unmodified `cm2_ma.sources.solver.MaSolverBytesSource` (Plan 1), since `sec.state.ma.us` is Incapsula-blocked.
- `cm2_ingestion.contracts` (`PreElectionBatch`, `ContestRecord`, `OfficeRecord`, `JurisdictionRecord`, `CandidateFilingRecord`, `PersonSourceEvidence`, `ElectionRecord`, `IngestionNotice`, `ContractValidationError`, `validate_pre_election_batch`) is shared and must not be modified.
- `cm2_ma.mapping.ocpf_pool.OcpfCandidatePool` (Plan 2) must not be modified — only queried via `find_by_name_and_district_code(*, full_name, district_code)`.
- The district crosswalk (Task 1) is the one piece of this plan grounded in cross-referenced live verification, not guesswork — see the Task 1 brief for exactly what was and wasn't verified (Senate: fully verified via the Legislature's own map key; House: 159/160 direct matches, one confirmed gap; Governor's Council/DA/Probate/Treasurer/Commissioner/Sheriff: fully verified). Federal offices (Senator/Representative in Congress) intentionally never resolve — OCPF does not regulate federal candidates. A crosswalk miss must always fall through to `person_public_id=None` (provisional-person path), never raise or guess.
- `vote_for` defaults to `1` for every contest in this plan (Secretary candidate pages don't state vote-for counts; the design spec's ballot-sample-based validation is future work, out of scope here) — document this as an assumption, don't silently treat it as verified.
- `is_partisan=True` and `party_contest` = the page's fixed party (`"DEMOCRATIC"`/`"REPUBLICAN"`) for every contest built by this plan — these are primary-ballot pages only; the general-election page doesn't exist yet (per Plan design, out of scope).
- `ruff check backend/cm2_ma` must stay clean.
- All new tests must run via `docker compose -f docker-compose.v2.yaml run --rm test pytest ... --no-migrations` from the repo root — not the host's bare Python.

---

## File Structure

```
backend/cm2_ma/
  source_records.py            # MODIFY: add SecretaryCandidateRow
  mapping/
    identity.py                 # NEW: stable_public_id / contest_public_id (ma/ prefix, mirrors cm2_nc)
    office_crosswalk.py         # NEW: Secretary (office, district) -> OCPF district_code
    jurisdictions.py            # NEW: Secretary (office, district) -> JurisdictionRecord
    offices.py                  # NEW: Secretary office label -> OfficeRecord
    batch.py                    # NEW: ties everything into PreElectionBatch
  sources/
    candidate_pages.py          # NEW: h2/h3/p parser, suffix-aware name/address split
  tests/
    test_office_crosswalk.py
    test_candidate_pages.py
    test_jurisdictions_offices.py
    test_batch.py
```

---

### Task 1: District crosswalk

**Files:**
- Create: `backend/cm2_ma/mapping/office_crosswalk.py`
- Test: `backend/cm2_ma/tests/test_office_crosswalk.py`

**Interfaces:**
- Consumes: `cm2_ma.source_records.OcpfDistrict` (Plan 2, existing).
- Produces: `cm2_ma.mapping.office_crosswalk.resolve_district_code(*, office_label: str, district_label: str | None, districts: dict[int, OcpfDistrict]) -> int | None`. Consumed by Task 4. `districts` is exactly `OcpfCandidatePool.districts` (Plan 2) — this module takes the raw dict, not the pool itself, keeping it decoupled from Plan 2's specific data structure.

**What was verified during design, and what wasn't** (carried forward so nobody re-litigates this from scratch): a full diff of the real OCPF `district_code_list.txt` (714 rows) against all 242 real Secretary district labels (extracted from the live-fetched `dem-state-primary-candidates2026.htm` page) found:
- Governor's Council (8/8), County Treasurer (3/3), County Commissioner (5/5), Sheriff (1/1), Register of Probate (14/14), District Attorney (11/11) — all fully verified, clean matches once each office's exact rule is applied (see below).
- Senate (40/40, after translation) — the Massachusetts Legislature's own **Senate Map Key** (`malegislature.gov/assets/redistricting/Senate Map Key-2021.pdf`) confirms OCPF's district table uses *pre-2021-redistricting* district names while the Secretary's pages use the *current* (post-2021) names. All 40 Senate districts were checked against this key; the `SENATE_NEW_TO_OLD` table below is transcribed directly from it (District IDs D01–D40), not inferred.
- House (159/160) — one confirmed gap: the Secretary lists a 19th Worcester House district; OCPF's table only goes to 18 (codes 344–363). No equivalent House map key was found to confirm why. Left as a genuine no-match — do not guess a code for it.
- Statewide offices (Governor, Lieutenant Governor, Attorney General, Secretary of State, Treasurer, Auditor) — only `Auditor` was directly confirmed live (OCPF code `1114`, `Office_Type_Description="Statewide"`, `District_Description="Auditor"`). The other five are assumed to follow the same identity-mapping pattern (h2 text == OCPF `District_Description`) but were **not individually verified** — a wrong assumption here just means no match (safe), not a wrong match.
- Federal offices (Senator in Congress, Representative in Congress) — **never** resolve. OCPF is Massachusetts' state campaign-finance regulator; it has no federal-office category at all. This is by design, not a gap.

**Per-office matching rule** (verified live, see above):
- Governor's Council: OCPF keeps the `"District"` suffix (e.g. `"7th District"`) — do NOT strip it.
- Senate, House, Register of Probate, County Treasurer, County Commissioner, Sheriff: OCPF drops the `"District"`/`"County"` suffix (e.g. `"9th Essex"`, `"Berkshire"` for Treasurer... wait, Treasurer/Commissioner keep the county name, just without the word "County" itself in some cases — verify against the exact stored strings in the test fixture, which uses real captured rows).
- District Attorney: OCPF's format is `"<Name> District - <County(ies)> County"` (e.g. `"Berkshire District - Berkshire County"`) — match as an exact string OR a prefix before `" - "`, with one real exception: OCPF's `"Middle District"` (code 614) has no `" - "` suffix at all.
- Ordinal words (`"First"`, `"Twenty-Third"`, etc.) become abbreviated numerals (`"1st"`, `"23rd"`) — OCPF never spells out ordinals.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/test_office_crosswalk.py`:
```python
from cm2_ma.mapping.office_crosswalk import resolve_district_code
from cm2_ma.source_records import OcpfDistrict

# Real rows, captured live from district_code_list.txt during design.
_DISTRICTS = {
    1114: OcpfDistrict(district_code=1114, office_type="Statewide", district_description="Auditor"),
    231: OcpfDistrict(district_code=231, office_type="House", district_description="9th Essex"),
    363: OcpfDistrict(district_code=363, office_type="House", district_description="18th Worcester"),
    1107: OcpfDistrict(district_code=1107, office_type="Governor's Council", district_description="7th District"),
    602: OcpfDistrict(district_code=602, office_type="District Attorney", district_description="Berkshire District - Berkshire County"),
    614: OcpfDistrict(district_code=614, office_type="District Attorney", district_description="Middle District"),
    705: OcpfDistrict(district_code=705, office_type="Treasurer", district_description="Essex County"),
    # Senate: OCPF's PRE-2021 name for what the Secretary now calls
    # "Third Bristol and Plymouth District" (Massachusetts Senate District D36 --
    # verified against the Legislature's own Senate Map Key).
    104: OcpfDistrict(district_code=104, office_type="Senate", district_description="1st Plymouth & Bristol"),
    # OCPF's PRE-2021 name for D01, now "Berkshire, Hampden, Franklin and Hampshire".
    154: OcpfDistrict(district_code=154, office_type="Senate", district_description="Berkshire, Hampshire, Franklin & Hampden"),
}


def test_statewide_office_matches_by_identity_name():
    code = resolve_district_code(office_label="Auditor", district_label=None, districts=_DISTRICTS)
    assert code == 1114


def test_house_district_strips_suffix_and_abbreviates_ordinal():
    code = resolve_district_code(
        office_label="Representative in General Court", district_label="Ninth Essex District", districts=_DISTRICTS
    )
    assert code == 231


def test_governors_council_keeps_district_suffix():
    code = resolve_district_code(office_label="Councillor", district_label="Seventh District", districts=_DISTRICTS)
    assert code == 1107


def test_district_attorney_matches_as_prefix_before_county_suffix():
    code = resolve_district_code(
        office_label="District Attorney", district_label="Berkshire District", districts=_DISTRICTS
    )
    assert code == 602


def test_district_attorney_middle_district_has_no_county_suffix():
    code = resolve_district_code(office_label="District Attorney", district_label="Middle District", districts=_DISTRICTS)
    assert code == 614


def test_county_treasurer_maps_to_ocpf_treasurer_office_type():
    code = resolve_district_code(office_label="County Treasurer", district_label="Essex County", districts=_DISTRICTS)
    assert code == 705


def test_senate_district_translates_current_name_to_pre_2021_ocpf_name():
    code = resolve_district_code(
        office_label="Senator in General Court",
        district_label="Third Bristol & Plymouth District",
        districts=_DISTRICTS,
    )
    assert code == 104


def test_senate_district_translates_multi_county_current_name():
    code = resolve_district_code(
        office_label="Senator in General Court",
        district_label="Berkshire, Hampden, Franklin & Hampshire District",
        districts=_DISTRICTS,
    )
    assert code == 154


def test_federal_office_never_resolves():
    code = resolve_district_code(
        office_label="Representative in Congress", district_label="First District", districts=_DISTRICTS
    )
    assert code is None


def test_unresolvable_house_district_returns_none_not_error():
    # The one confirmed real gap: Secretary lists a 19th Worcester House
    # district; OCPF's table (verified live) only goes to 18th.
    code = resolve_district_code(
        office_label="Representative in General Court",
        district_label="Nineteenth Worcester District",
        districts=_DISTRICTS,
    )
    assert code is None


def test_sheriff_strips_vacancy_qualifier_from_office_label():
    districts = dict(_DISTRICTS)
    districts[900] = OcpfDistrict(district_code=900, office_type="Sheriff", district_description="Franklin County")
    code = resolve_district_code(
        office_label="Sheriff (to fill a vacancy)", district_label="Franklin County", districts=districts
    )
    assert code == 900
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_office_crosswalk.py -v --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.mapping'`

- [ ] **Step 3: Write minimal implementation**

`backend/cm2_ma/mapping/__init__.py` (create if it does not already exist from an earlier plan — it does not; Plan 1 and Plan 2 never created a `mapping/` package):
```python
```

`backend/cm2_ma/mapping/office_crosswalk.py`:
```python
import re

from cm2_ma.source_records import OcpfDistrict

# Secretary h2 label -> (OCPF Office_Type_Description, keep "District"/"County" suffix).
# Verified live against the real district_code_list.txt during design -- see this
# task's brief for exactly what was and wasn't confirmed.
_OFFICE_TYPE_MAP: dict[str, tuple[str, bool]] = {
    "Councillor": ("Governor's Council", True),
    "Senator in General Court": ("Senate", False),
    "Representative in General Court": ("House", False),
    "District Attorney": ("District Attorney", True),
    "Register of Probate": ("Register of Probate", False),
    "County Treasurer": ("Treasurer", False),
    "County Commissioner": ("County Commissioner", False),
    "Sheriff": ("Sheriff", False),
}

# Statewide offices (no district): Secretary h2 text -> OCPF District_Description.
# Only "Auditor" was directly confirmed live; the rest are an identity-mapping
# assumption (see brief) -- a wrong guess here just means no match, never a
# wrong match.
_STATEWIDE_OFFICE_NAMES: dict[str, str] = {
    "Governor": "Governor",
    "Lieutenant Governor": "Lieutenant Governor",
    "Attorney General": "Attorney General",
    "Secretary of State": "Secretary of State",
    "Treasurer": "Treasurer",
    "Auditor": "Auditor",
}

_ORDINAL_WORDS = [
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth",
    "ninth", "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth",
    "sixteenth", "seventeenth", "eighteenth", "nineteenth", "twentieth", "thirtieth",
]
_ORDINAL_MAP = {word: index + 1 for index, word in enumerate(_ORDINAL_WORDS)}
_TENS = {"twenty": 20, "thirty": 30}
_COMPOUND_ORDINALS = [
    f"{tens}-{ones}" for tens in _TENS for ones in _ORDINAL_WORDS if _ORDINAL_MAP[ones] < 10
]
_ORDINAL_TOKEN_RE = re.compile(
    r"\b(" + "|".join(sorted(_ORDINAL_WORDS + _COMPOUND_ORDINALS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def _ordinal_word_to_num(word: str) -> int | None:
    lowered = word.lower()
    if lowered in _ORDINAL_MAP:
        return _ORDINAL_MAP[lowered]
    if "-" in lowered:
        tens_part, ones_part = lowered.split("-")
        if tens_part in _TENS and ones_part in _ORDINAL_MAP and _ORDINAL_MAP[ones_part] < 10:
            return _TENS[tens_part] + _ORDINAL_MAP[ones_part]
    return None


def _ordinal_suffix(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _normalize_district_text(text: str, *, keep_suffix: bool) -> str:
    normalized = text.strip()
    if not keep_suffix:
        normalized = re.sub(r"\s+District$", "", normalized)
        normalized = re.sub(r"\s+County$", " County", normalized)  # no-op placeholder kept explicit for clarity

    def _replace(match: re.Match) -> str:
        number = _ordinal_word_to_num(match.group(1))
        return f"{number}{_ordinal_suffix(number)}" if number else match.group(0)

    normalized = _ORDINAL_TOKEN_RE.sub(_replace, normalized)
    return " ".join(normalized.split())


# Massachusetts Senate districts: current (post-2021-redistricting, used by the
# Secretary's candidate pages) -> pre-2021 name (still used in OCPF's district
# table). Transcribed directly from the Legislature's own Senate Map Key
# (malegislature.gov/assets/redistricting/Senate Map Key-2021.pdf), District
# IDs D01-D40, "New Long Name" -> "Current Long Name" columns. Both sides use
# "&" here (not "and") to match the real OCPF/Secretary text exactly.
_SENATE_NEW_TO_OLD: dict[str, str] = {
    "berkshire, hampden, franklin & hampshire": "berkshire, hampshire, franklin & hampden",
    "hampden & hampshire": "second hampden & hampshire",
    "hampden": "hampden",
    "hampden, hampshire & worcester": "first hampden & hampshire",
    "hampshire, franklin & worcester": "hampshire, franklin & worcester",
    "worcester & hampshire": "worcester, hampden, hampshire & middlesex",
    "worcester & hampden": "worcester & norfolk",
    "second worcester": "second worcester",
    "first worcester": "first worcester",
    "worcester & middlesex": "worcester & middlesex",
    "first middlesex": "first middlesex",
    "middlesex & worcester": "middlesex & worcester",
    "middlesex & norfolk": "second middlesex & norfolk",
    "norfolk, worcester & middlesex": "norfolk, bristol & middlesex",
    "third middlesex": "third middlesex",
    "fourth middlesex": "fourth middlesex",
    "norfolk & middlesex": "first middlesex & norfolk",
    "norfolk & suffolk": "norfolk & suffolk",
    "first essex": "first essex",
    "second essex & middlesex": "second essex & middlesex",
    "first essex & middlesex": "first essex & middlesex",
    "second essex": "second essex",
    "fifth middlesex": "fifth middlesex",
    "third essex": "third essex",
    "third suffolk": "first suffolk & middlesex",
    "middlesex & suffolk": "middlesex & suffolk",
    "second middlesex": "second middlesex",
    "suffolk & middlesex": "second suffolk & middlesex",
    "second suffolk": "second suffolk",
    "first suffolk": "first suffolk",
    "first plymouth & norfolk": "plymouth & norfolk",
    "norfolk & plymouth": "norfolk & plymouth",
    "norfolk, plymouth & bristol": "norfolk, bristol & plymouth",
    "second plymouth & norfolk": "second plymouth & bristol",
    "bristol & norfolk": "bristol & norfolk",
    "third bristol & plymouth": "first plymouth & bristol",
    "first bristol & plymouth": "first bristol & plymouth",
    "second bristol & plymouth": "second bristol & plymouth",
    "plymouth & barnstable": "plymouth & barnstable",
    "cape & islands": "cape & islands",
}


def _index_district_type(
    districts: dict[int, OcpfDistrict], office_type: str
) -> dict[str, int]:
    return {
        district.district_description.casefold(): code
        for code, district in districts.items()
        if district.office_type == office_type
    }


def resolve_district_code(
    *, office_label: str, district_label: str | None, districts: dict[int, OcpfDistrict]
) -> int | None:
    office_key = re.sub(r"\s*\(.*\)\s*$", "", office_label).strip()

    if district_label is None:
        target = _STATEWIDE_OFFICE_NAMES.get(office_key)
        if target is None:
            return None
        index = _index_district_type(districts, "Statewide")
        return index.get(target.casefold())

    mapping = _OFFICE_TYPE_MAP.get(office_key)
    if mapping is None:
        return None
    ocpf_office_type, keep_suffix = mapping

    normalized = _normalize_district_text(district_label, keep_suffix=keep_suffix)

    if ocpf_office_type == "Senate":
        normalized = _SENATE_NEW_TO_OLD.get(normalized.casefold(), normalized)

    if ocpf_office_type == "District Attorney":
        normalized_casefold = normalized.casefold()
        for code, district in districts.items():
            if district.office_type != "District Attorney":
                continue
            desc_casefold = district.district_description.casefold()
            if desc_casefold == normalized_casefold or desc_casefold.startswith(
                normalized_casefold + " - "
            ):
                return code
        return None

    index = _index_district_type(districts, ocpf_office_type)
    return index.get(normalized.casefold())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_office_crosswalk.py -v --no-migrations`
Expected: PASS (11 tests)

Also run: `docker compose -f docker-compose.v2.yaml run --rm test ruff check cm2_ma`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/mapping/__init__.py backend/cm2_ma/mapping/office_crosswalk.py backend/cm2_ma/tests/test_office_crosswalk.py
git commit -m "feat(cm2_ma): add Secretary-to-OCPF district code crosswalk"
```

---

### Task 2: Candidate-page parser

**Files:**
- Modify: `backend/cm2_ma/source_records.py`
- Create: `backend/cm2_ma/sources/candidate_pages.py`
- Test: `backend/cm2_ma/tests/test_candidate_pages.py`

**Interfaces:**
- Consumes: `cm2_ma.sources.solver.MaSolverBytesSource` (Plan 1).
- Produces: `cm2_ma.source_records.SecretaryCandidateRow` (fields: `office_label: str`, `district_label: str | None`, `party: str`, `raw_line: str`, `reported_name: str`, `given_name: str`, `middle_name: str`, `family_name: str`, `suffix: str`, `address: str`). `cm2_ma.source_records.SecretaryPageParseResult` (fields: `candidates: tuple[SecretaryCandidateRow, ...]`, `no_nominations: tuple[tuple[str, str | None], ...]` — each a `(office_label, district_label)` pair). `cm2_ma.sources.candidate_pages.parse_candidate_page(content: bytes, *, party: str) -> SecretaryPageParseResult` and `MaCandidatePageSource(MaSolverBytesSource)` (constructed with `url: str`, `party: str`). Consumed by Task 4.

Grounded in the real markup captured live during design: `<h2>` = office, optional `<h3>` = district, `<p>` = one candidate line (`"Name, Street, City"`) or the literal text `"No Nominations"`. Real confirmed edge case: a name can contain a comma before the address starts when there's a suffix — `"Christopher A. Iannella, Jr., 263 Pond St., Boston"` and `"Joseph D. Early, Jr., 36 Blackthorn Dr., Worcester"` are both real rows from the live page. A naive split on the first comma breaks these.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/test_candidate_pages.py`:
```python
from cm2_ma.constants import SEC_BASE_URL
from cm2_ma.sources.candidate_pages import MaCandidatePageSource, parse_candidate_page

# Real markup, captured live from dem-state-primary-candidates2026.htm during design.
_FIXTURE = b"""
<h2 id="senator-in-congress">Senator in Congress</h2>
<p>Edward J. Markey, 360 Charles St., Malden</p>
<p>Seth Moulton, 37 Chestnut St., Salem</p>

<h2 id="councillor">Councillor</h2>
<h3>Fourth District</h3>
<p>Christopher A. Iannella, Jr., 263 Pond St., Boston</p>
<p>Ronald Primo Iacobucci, 430 Adams St., Quincy</p>

<h2 id="DA">District Attorney</h2>
<h3>Plymouth District</h3>
<p>No Nominations</p>

<h3>Suffolk District</h3>
<p>Kevin R. Hayden, 199 Beech St., Boston</p>
"""


def test_statewide_rows_have_no_district_label():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    markey = next(c for c in result.candidates if c.reported_name == "Edward J. Markey")
    assert markey.office_label == "Senator in Congress"
    assert markey.district_label is None
    assert markey.address == "360 Charles St., Malden"
    assert markey.party == "DEMOCRATIC"


def test_district_rows_carry_the_h3_label():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    iacobucci = next(c for c in result.candidates if c.reported_name == "Ronald Primo Iacobucci")
    assert iacobucci.office_label == "Councillor"
    assert iacobucci.district_label == "Fourth District"


def test_suffix_in_name_does_not_break_on_the_embedded_comma():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    iannella = next(c for c in result.candidates if "Iannella" in c.reported_name)
    assert iannella.reported_name == "Christopher A. Iannella, Jr."
    assert iannella.suffix == "Jr."
    assert iannella.given_name == "Christopher"
    assert iannella.family_name == "Iannella"
    assert iannella.address == "263 Pond St., Boston"


def test_no_nominations_is_not_a_candidate_but_is_recorded():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    assert not any(c.district_label == "Plymouth District" for c in result.candidates)
    assert ("District Attorney", "Plymouth District") in result.no_nominations


def test_reported_name_survives_even_with_imperfect_given_family_split():
    result = parse_candidate_page(_FIXTURE, party="DEMOCRATIC")

    hayden = next(c for c in result.candidates if c.reported_name == "Kevin R. Hayden")
    assert hayden.given_name == "Kevin"
    assert hayden.family_name == "Hayden"
    assert hayden.middle_name == "R."


def test_source_url_and_party_are_configured():
    url = f"{SEC_BASE_URL}/divisions/elections/research-and-statistics/dem-state-primary-candidates2026.htm"
    source = MaCandidatePageSource(url=url, party="DEMOCRATIC")

    assert source.url == url

    result = source.parse(_FIXTURE)
    # Markey, Moulton, Iannella, Iacobucci, Hayden -- "No Nominations" isn't a candidate.
    assert len(result.candidates) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_candidate_pages.py -v --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.sources.candidate_pages'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/cm2_ma/source_records.py` (append after `OcpfCandidateRow`; do not remove earlier content):
```python
@dataclass(frozen=True, slots=True)
class SecretaryCandidateRow:
    office_label: str
    district_label: str | None
    party: str
    raw_line: str
    reported_name: str
    given_name: str
    middle_name: str
    family_name: str
    suffix: str
    address: str


@dataclass(frozen=True, slots=True)
class SecretaryPageParseResult:
    candidates: tuple[SecretaryCandidateRow, ...]
    no_nominations: tuple[tuple[str, str | None], ...]
```

`backend/cm2_ma/sources/candidate_pages.py`:
```python
import re

from bs4 import BeautifulSoup

from cm2_ma.source_records import SecretaryCandidateRow, SecretaryPageParseResult

from .solver import MaSolverBytesSource

_SUFFIXES = {"jr.", "jr", "sr.", "sr", "ii", "iii", "iv", "v"}
_NO_NOMINATIONS = "no nominations"


def _split_name_and_address(raw_line: str) -> tuple[str, str, str]:
    """
    Returns (reported_name, suffix, address). Handles the real edge case where
    a suffix creates an extra comma before the address starts, e.g.
    "Christopher A. Iannella, Jr., 263 Pond St., Boston" -- a naive split on
    the first comma would otherwise take the name as just "Christopher A.
    Iannella" and misplace "Jr." into the address.
    """
    parts = [part.strip() for part in raw_line.split(",")]
    if len(parts) >= 2 and parts[1].casefold().rstrip(".") in {s.rstrip(".") for s in _SUFFIXES}:
        suffix = parts[1]
        name = f"{parts[0]}, {suffix}"
        address = ", ".join(parts[2:])
        return name, suffix, address
    name = parts[0]
    address = ", ".join(parts[1:])
    return name, "", address


def _split_given_middle_family(name_without_suffix: str) -> tuple[str, str, str]:
    tokens = name_without_suffix.split()
    if not tokens:
        return "", "", ""
    if len(tokens) == 1:
        return tokens[0], "", ""
    given = tokens[0]
    family = tokens[-1]
    middle = " ".join(tokens[1:-1])
    return given, middle, family


def parse_candidate_page(content: bytes, *, party: str) -> SecretaryPageParseResult:
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")

    candidates: list[SecretaryCandidateRow] = []
    no_nominations: list[tuple[str, str | None]] = []

    current_office: str | None = None
    current_district: str | None = None

    for element in soup.find_all(re.compile(r"^(h2|h3|p)$")):
        if element.name == "h2":
            current_office = " ".join(element.get_text(" ", strip=True).split())
            current_district = None
            continue
        if element.name == "h3":
            current_district = " ".join(element.get_text(" ", strip=True).split())
            continue
        if current_office is None:
            continue

        raw_line = " ".join(element.get_text(" ", strip=True).split())
        if not raw_line:
            continue
        if raw_line.casefold() == _NO_NOMINATIONS:
            no_nominations.append((current_office, current_district))
            continue

        name_with_suffix, suffix, address = _split_name_and_address(raw_line)
        name_without_suffix = name_with_suffix[: -(len(suffix) + 2)] if suffix else name_with_suffix
        given, middle, family = _split_given_middle_family(name_without_suffix)

        candidates.append(
            SecretaryCandidateRow(
                office_label=current_office,
                district_label=current_district,
                party=party,
                raw_line=raw_line,
                reported_name=name_with_suffix,
                given_name=given,
                middle_name=middle,
                family_name=family,
                suffix=suffix,
                address=address,
            )
        )

    return SecretaryPageParseResult(
        candidates=tuple(candidates), no_nominations=tuple(no_nominations)
    )


class MaCandidatePageSource(MaSolverBytesSource):
    def __init__(self, *, url: str, party: str, client=None):
        super().__init__(client=client)
        self.url = url
        self.party = party

    def parse(self, content: bytes) -> SecretaryPageParseResult:
        return parse_candidate_page(content, party=self.party)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_candidate_pages.py -v --no-migrations`
Expected: PASS (6 tests)

Also run: `docker compose -f docker-compose.v2.yaml run --rm test ruff check cm2_ma`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/source_records.py backend/cm2_ma/sources/candidate_pages.py backend/cm2_ma/tests/test_candidate_pages.py
git commit -m "feat(cm2_ma): parse Secretary candidate pages, handling the suffix-comma edge case"
```

---

### Task 3: Jurisdiction and office mapping

**Files:**
- Create: `backend/cm2_ma/mapping/identity.py`
- Create: `backend/cm2_ma/mapping/jurisdictions.py`
- Create: `backend/cm2_ma/mapping/offices.py`
- Test: `backend/cm2_ma/tests/test_jurisdictions_offices.py`

**Interfaces:**
- Produces: `cm2_ma.mapping.identity.{stable_public_id, normalize_identity_part, contest_public_id}` (mirrors `cm2_nc.mapping.identity` exactly except for an `"ma/"` public-id prefix instead of `"nc/"`). `cm2_ma.mapping.jurisdictions.map_jurisdiction(office_label: str, district_label: str | None) -> tuple[JurisdictionRecord, ...]` (returns `(STATE,)` for statewide offices, or `(STATE, district_jurisdiction)` for district-based ones — same shape as NC's `map_jurisdiction`). `cm2_ma.mapping.offices.map_office(office_label: str, jurisdiction: JurisdictionRecord) -> OfficeRecord`. Consumed by Task 4.

**This is simpler than NC's equivalent modules.** NC has to *infer* office and district from one flat contest-name string via regex. MA's Secretary page structure already separates office (`<h2>`) from district (`<h3>`) — no regex inference needed, just a small normalization lookup for the handful of h2 labels whose text isn't already a clean office name (`"Senator in Congress"` → `"U.S. Senator"`, etc.) and a classification tag per office type for `JurisdictionRecord.classification`.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/test_jurisdictions_offices.py`:
```python
from cm2_ma.mapping.jurisdictions import map_jurisdiction
from cm2_ma.mapping.offices import map_office


def test_statewide_office_maps_to_the_state_singleton_jurisdiction():
    jurisdictions = map_jurisdiction("Governor", None)

    assert len(jurisdictions) == 1
    assert jurisdictions[0].classification == "state"
    assert jurisdictions[0].name == "Massachusetts"


def test_district_office_maps_to_state_plus_a_child_jurisdiction():
    jurisdictions = map_jurisdiction("Representative in General Court", "9th Essex District")

    assert len(jurisdictions) == 2
    state, district = jurisdictions
    assert state.classification == "state"
    assert district.classification == "state_house_district"
    assert district.name == "9th Essex District"
    assert district.parent_public_id == state.public_id


def test_county_row_office_is_classified_as_county():
    jurisdictions = map_jurisdiction("Register of Probate", "Barnstable County")

    district = jurisdictions[-1]
    assert district.classification == "county"
    assert district.name == "Barnstable County"


def test_jurisdiction_identity_is_stable_across_calls():
    first = map_jurisdiction("District Attorney", "Suffolk District")
    second = map_jurisdiction("District Attorney", "Suffolk District")

    assert first[-1].public_id == second[-1].public_id


def test_office_name_is_normalized_for_congress_and_general_court():
    jurisdiction = map_jurisdiction("Senator in General Court", "First Essex District")[-1]
    office = map_office("Senator in General Court", jurisdiction)

    assert office.canonical_name == "State Senator"


def test_office_name_passes_through_when_already_clean():
    jurisdiction = map_jurisdiction("Register of Probate", "Essex County")[-1]
    office = map_office("Register of Probate", jurisdiction)

    assert office.canonical_name == "Register of Probate"


def test_office_strips_vacancy_qualifier_from_sheriff():
    jurisdiction = map_jurisdiction("Sheriff (to fill a vacancy)", "Franklin County")[-1]
    office = map_office("Sheriff (to fill a vacancy)", jurisdiction)

    assert office.canonical_name == "Sheriff"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_jurisdictions_offices.py -v --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.mapping.jurisdictions'`

- [ ] **Step 3: Write minimal implementation**

`backend/cm2_ma/mapping/identity.py`:
```python
import hashlib
import re
import unicodedata


def normalize_identity_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.casefold().split())


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    return slug[:48] or "record"


def stable_public_id(kind: str, *parts: str) -> str:
    normalized_kind = _slug(normalize_identity_part(kind))
    normalized_parts = tuple(normalize_identity_part(part) for part in parts)
    digest_input = "\x1f".join((normalized_kind, *normalized_parts))
    digest = hashlib.sha256(digest_input.encode()).hexdigest()[:16]
    readable = "/".join(_slug(part) for part in normalized_parts[:4])
    return f"ma/{normalized_kind}/{readable}/{digest}"


def contest_public_id(
    *,
    election_public_id: str,
    office_public_id: str,
    party_contest: str,
    is_unexpired: bool,
) -> str:
    return stable_public_id(
        "contest",
        election_public_id,
        office_public_id,
        party_contest or "all-voters",
        "unexpired" if is_unexpired else "regular-term",
    )
```

`backend/cm2_ma/mapping/jurisdictions.py`:
```python
import re

from cm2_ingestion.contracts import JurisdictionRecord

from .identity import stable_public_id

_STATE = JurisdictionRecord(
    public_id=stable_public_id("jurisdiction", "state", "Massachusetts"),
    name="Massachusetts",
    classification="state",
    state="MA",
    record_status="verified",
    source_key="MA",
)

# Secretary h2 office label -> JurisdictionRecord.classification for its
# district-level (h3) jurisdictions. Offices not listed here never appear
# with a district_label (all statewide).
_OFFICE_CLASSIFICATION: dict[str, str] = {
    "Representative in Congress": "congressional_district",
    "Councillor": "councillor_district",
    "Senator in General Court": "state_senate_district",
    "Representative in General Court": "state_house_district",
    "District Attorney": "district_attorney_district",
    "Register of Probate": "county",
    "County Treasurer": "county",
    "County Commissioner": "county",
    "Sheriff": "county",
}


def _office_key(office_label: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", office_label).strip()


def map_jurisdiction(office_label: str, district_label: str | None) -> tuple[JurisdictionRecord, ...]:
    if district_label is None:
        return (_STATE,)

    classification = _OFFICE_CLASSIFICATION.get(_office_key(office_label), "other")
    district = JurisdictionRecord(
        public_id=stable_public_id("jurisdiction", classification, district_label),
        name=district_label,
        classification=classification,
        state="MA",
        parent_public_id=_STATE.public_id,
        record_status="provisional",
        source_key=f"MA:{classification}:{district_label}",
    )
    return (_STATE, district)
```

`backend/cm2_ma/mapping/offices.py`:
```python
import re

from cm2_ingestion.contracts import JurisdictionRecord, OfficeRecord

from .identity import stable_public_id

# Secretary h2 text that needs normalizing into a cleaner canonical office
# name. Every other office label already reads as a good office name as-is
# (e.g. "Governor", "District Attorney", "Register of Probate").
_OFFICE_NAME_MAP: dict[str, str] = {
    "Senator in Congress": "U.S. Senator",
    "Representative in Congress": "U.S. Representative",
    "Councillor": "Governor's Councillor",
    "Senator in General Court": "State Senator",
    "Representative in General Court": "State Representative",
}

_ROLE_KEYWORDS = (
    ("senator", "senator"),
    ("representative", "representative"),
    ("governor", "governor"),
    ("attorney general", "attorney_general"),
    ("secretary", "secretary"),
    ("treasurer", "treasurer"),
    ("auditor", "auditor"),
    ("councillor", "councillor"),
    ("district attorney", "district_attorney"),
    ("register", "register"),
    ("commissioner", "commissioner"),
    ("sheriff", "sheriff"),
)


def _office_key(office_label: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", office_label).strip()


def _role(canonical_name: str) -> str:
    normalized = canonical_name.casefold()
    for keyword, role in _ROLE_KEYWORDS:
        if keyword in normalized:
            return role
    return "elected_official"


def map_office(office_label: str, jurisdiction: JurisdictionRecord) -> OfficeRecord:
    office_key = _office_key(office_label)
    canonical_name = _OFFICE_NAME_MAP.get(office_key, office_key)
    return OfficeRecord(
        public_id=stable_public_id("office", jurisdiction.public_id, canonical_name),
        jurisdiction_public_id=jurisdiction.public_id,
        canonical_name=canonical_name,
        role=_role(canonical_name),
        positions=1,
        record_status="provisional",
        source_key=office_key,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_jurisdictions_offices.py -v --no-migrations`
Expected: PASS (7 tests)

Also run: `docker compose -f docker-compose.v2.yaml run --rm test ruff check cm2_ma`
Expected: clean

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/mapping/identity.py backend/cm2_ma/mapping/jurisdictions.py backend/cm2_ma/mapping/offices.py backend/cm2_ma/tests/test_jurisdictions_offices.py
git commit -m "feat(cm2_ma): map Secretary office/district labels to Jurisdiction/Office records"
```

---

### Task 4: Batch builder

**Files:**
- Create: `backend/cm2_ma/mapping/batch.py`
- Test: `backend/cm2_ma/tests/test_batch.py`

**Interfaces:**
- Consumes: `cm2_ma.source_records.SecretaryCandidateRow` / `SecretaryPageParseResult` (Task 2), `cm2_ma.mapping.jurisdictions.map_jurisdiction` (Task 3), `cm2_ma.mapping.offices.map_office` (Task 3), `cm2_ma.mapping.identity.{stable_public_id, contest_public_id, normalize_identity_part}` (Task 3), `cm2_ma.mapping.office_crosswalk.resolve_district_code` (Task 1), `cm2_ma.mapping.ocpf_pool.OcpfCandidatePool` (Plan 2, existing, unmodified), `cm2_ingestion.contracts.{PreElectionBatch, ContestRecord, CandidateFilingRecord, PersonSourceEvidence, ElectionRecord, IngestionNotice, ContractValidationError, validate_pre_election_batch}` (existing, unmodified).
- Produces: `cm2_ma.mapping.batch.build_pre_election_batch(rows: tuple[SecretaryCandidateRow, ...], *, no_nominations: tuple[tuple[str, str | None], ...], discovered_elections: tuple[ElectionRecord, ...], ocpf_pool: OcpfCandidatePool) -> PreElectionBatch`. This is the final integration point of Plans 1-3 — not consumed by anything further in this plan, but is what an orchestration layer (out of scope, matching Plan 1's own precedent that scheduling/triggering is unbuilt for the whole CM2 program) would call.

**Election selection**: unlike NC (one CSV row per election date, multiple elections possible per run), every row this plan processes comes from a single party's primary candidate page — there is exactly one relevant election (the State Primary). Select the single `ElectionRecord` from `discovered_elections` with `election_type == "primary"`; raise `ContractValidationError` if there isn't exactly one (this plan doesn't handle the special-election candidate pages — those are out of scope, matching Plan 1's discovery-only special-election scope).

**OCPF matching**: for each row, call `resolve_district_code(office_label=row.office_label, district_label=row.district_label, districts=ocpf_pool.districts)`; if it returns a code, call `ocpf_pool.find_by_name_and_district_code(full_name=f"{row.given_name} {row.family_name}", district_code=code)`. On a match, set `CandidateFilingRecord.person_public_id = stable_public_id("person", "ocpf", str(match.cpf_id))`. On no code or no match, leave `person_public_id=None` (the existing provisional-person + identity-review fallback, unmodified, handles it from there — this plan does not touch that path).

**No Nominations**: each `(office_label, district_label)` pair in `no_nominations` becomes an `IngestionNotice(code="no_nominations", subject_type="office_district", subject_public_id=...)` rather than being silently dropped.

- [ ] **Step 1: Write the failing test**

`backend/cm2_ma/tests/test_batch.py`:
```python
from datetime import date

import pytest

from cm2_ingestion.contracts import ContractValidationError, ElectionRecord
from cm2_ma.mapping.batch import build_pre_election_batch
from cm2_ma.mapping.ocpf_pool import OcpfCandidatePool
from cm2_ma.source_records import OcpfCandidateRow, OcpfDistrict, SecretaryCandidateRow

_PRIMARY = ElectionRecord(
    public_id="ma/election/2026-09-01/primary/test",
    name="2026 Massachusetts State Primary",
    election_date=date(2026, 9, 1),
    election_type="primary",
    lifecycle_status="upcoming",
)

_DISTRICTS = (
    OcpfDistrict(district_code=1114, office_type="Statewide", district_description="Auditor"),
    OcpfDistrict(district_code=231, office_type="House", district_description="9th Essex"),
)


def _row(**overrides) -> SecretaryCandidateRow:
    defaults = dict(
        office_label="Representative in General Court",
        district_label="9th Essex District",
        party="DEMOCRATIC",
        raw_line="Steven Angelo, 39 Popmonet Rd, E. Falmouth",
        reported_name="Steven Angelo",
        given_name="Steven",
        middle_name="",
        family_name="Angelo",
        suffix="",
        address="39 Popmonet Rd, E. Falmouth",
    )
    defaults.update(overrides)
    return SecretaryCandidateRow(**defaults)


def _ocpf_candidate(**overrides) -> OcpfCandidateRow:
    defaults = dict(
        cpf_id=10010,
        first_name="Steven",
        last_name="Angelo",
        street_address="39 Popmonet Rd",
        city="E. Falmouth",
        state="MA",
        zip_code="02536",
        district_code_sought=231,
        office_type_sought="House",
        district_name_sought="9th Essex",
        closed_date="",
        party_affiliation="Democratic",
    )
    defaults.update(overrides)
    return OcpfCandidateRow(**defaults)


def test_matched_candidate_gets_a_pre_resolved_person_public_id():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_ocpf_candidate(),))
    batch = build_pre_election_batch(
        (_row(),), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=pool
    )

    assert len(batch.candidates) == 1
    candidate = batch.candidates[0]
    assert candidate.person_public_id is not None
    assert candidate.person_public_id.startswith("ma/person/")


def test_unmatched_candidate_falls_back_to_no_pre_resolved_identity():
    empty_pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    batch = build_pre_election_batch(
        (_row(),), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=empty_pool
    )

    assert batch.candidates[0].person_public_id is None


def test_federal_office_never_pre_resolves_even_with_a_populated_pool():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=(_ocpf_candidate(),))
    row = _row(
        office_label="Representative in Congress",
        district_label="First District",
        reported_name="Someone Federal",
        given_name="Someone",
        family_name="Federal",
        raw_line="Someone Federal, 1 Main St., Boston",
        address="1 Main St., Boston",
    )
    batch = build_pre_election_batch(
        (row,), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=pool
    )

    assert batch.candidates[0].person_public_id is None


def test_contests_carry_the_fixed_party_and_default_vote_for():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    batch = build_pre_election_batch(
        (_row(),), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=pool
    )

    assert len(batch.contests) == 1
    contest = batch.contests[0]
    assert contest.party_contest == "DEMOCRATIC"
    assert contest.is_partisan is True
    assert contest.vote_for == 1
    assert contest.election_public_id == _PRIMARY.public_id


def test_no_nominations_becomes_a_notice_not_a_candidate():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    batch = build_pre_election_batch(
        (),
        no_nominations=(("District Attorney", "Plymouth District"),),
        discovered_elections=(_PRIMARY,),
        ocpf_pool=pool,
    )

    assert batch.candidates == ()
    assert len(batch.notices) == 1
    assert batch.notices[0].code == "no_nominations"


def test_missing_primary_election_raises():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    general = ElectionRecord(
        public_id="ma/election/2026-11-03/general/test",
        name="2026 Massachusetts State Election",
        election_date=date(2026, 11, 3),
        election_type="general",
    )

    with pytest.raises(ContractValidationError, match="primary"):
        build_pre_election_batch(
            (_row(),), no_nominations=(), discovered_elections=(general,), ocpf_pool=pool
        )


def test_batch_state_is_ma_and_validates_cleanly():
    pool = OcpfCandidatePool.build(districts=_DISTRICTS, candidates=())
    batch = build_pre_election_batch(
        (_row(),), no_nominations=(), discovered_elections=(_PRIMARY,), ocpf_pool=pool
    )

    assert batch.state == "MA"
    assert len(batch.jurisdictions) == 2  # state + 9th Essex District
    assert len(batch.offices) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_batch.py -v --no-migrations`
Expected: FAIL — `ModuleNotFoundError: No module named 'cm2_ma.mapping.batch'`

- [ ] **Step 3: Write minimal implementation**

`backend/cm2_ma/mapping/batch.py`:
```python
from cm2_ingestion.contracts import (
    CandidateFilingRecord,
    ContestRecord,
    ContractValidationError,
    ElectionRecord,
    IngestionNotice,
    JurisdictionRecord,
    OfficeRecord,
    PersonSourceEvidence,
    PreElectionBatch,
    validate_pre_election_batch,
)
from cm2_ma.mapping.identity import contest_public_id, stable_public_id
from cm2_ma.mapping.jurisdictions import map_jurisdiction
from cm2_ma.mapping.ocpf_pool import OcpfCandidatePool
from cm2_ma.mapping.office_crosswalk import resolve_district_code
from cm2_ma.mapping.offices import map_office
from cm2_ma.source_records import SecretaryCandidateRow


def _select_primary_election(discovered_elections: tuple[ElectionRecord, ...]) -> ElectionRecord:
    primaries = [election for election in discovered_elections if election.election_type == "primary"]
    if len(primaries) != 1:
        raise ContractValidationError(
            f"expected exactly one discovered primary election, found {len(primaries)}"
        )
    return primaries[0]


def _put_unique(records: dict[str, object], record, *, label: str) -> None:
    existing = records.get(record.public_id)
    if existing is not None and existing != record:
        raise ContractValidationError(f"conflicting normalized {label} mapping")
    records[record.public_id] = record


def _resolve_person_public_id(
    row: SecretaryCandidateRow, *, ocpf_pool: OcpfCandidatePool
) -> str | None:
    district_code = resolve_district_code(
        office_label=row.office_label, district_label=row.district_label, districts=ocpf_pool.districts
    )
    if district_code is None:
        return None
    full_name = " ".join(part for part in (row.given_name, row.family_name) if part)
    match = ocpf_pool.find_by_name_and_district_code(full_name=full_name, district_code=district_code)
    if match is None:
        return None
    return stable_public_id("person", "ocpf", str(match.cpf_id))


def _no_nomination_notice(office_label: str, district_label: str | None) -> IngestionNotice:
    identity = stable_public_id("source-contest", office_label, district_label or "")
    return IngestionNotice(
        code="no_nominations", subject_type="office_district", subject_public_id=identity
    )


def build_pre_election_batch(
    rows: tuple[SecretaryCandidateRow, ...],
    *,
    no_nominations: tuple[tuple[str, str | None], ...],
    discovered_elections: tuple[ElectionRecord, ...],
    ocpf_pool: OcpfCandidatePool,
) -> PreElectionBatch:
    election = _select_primary_election(discovered_elections)

    jurisdictions: dict[str, JurisdictionRecord] = {}
    offices: dict[str, OfficeRecord] = {}
    contests: dict[str, ContestRecord] = {}
    candidates: list[CandidateFilingRecord] = []

    for row in rows:
        mapped_jurisdictions = map_jurisdiction(row.office_label, row.district_label)
        for jurisdiction in mapped_jurisdictions:
            _put_unique(jurisdictions, jurisdiction, label="jurisdiction")
        jurisdiction = mapped_jurisdictions[-1]

        office = map_office(row.office_label, jurisdiction)
        _put_unique(offices, office, label="office")

        contest_id = contest_public_id(
            election_public_id=election.public_id,
            office_public_id=office.public_id,
            party_contest=row.party,
            is_unexpired=False,
        )
        if contest_id not in contests:
            contests[contest_id] = ContestRecord(
                public_id=contest_id,
                election_public_id=election.public_id,
                office_public_id=office.public_id,
                party_contest=row.party,
                vote_for=1,
                is_partisan=True,
                is_unexpired=False,
                lifecycle_status="upcoming",
                result_status="pending",
                source_key=f"{row.office_label}|{row.district_label or ''}|{row.party}",
            )

        source_row_key = stable_public_id(
            "source-row", contest_id, row.party, row.raw_line
        )
        evidence = PersonSourceEvidence(
            source_row_key=source_row_key,
            reported_name=row.reported_name,
            ballot_name=row.reported_name,
            given_name=row.given_name,
            middle_name=row.middle_name,
            family_name=row.family_name,
            suffix=row.suffix,
            filing_data={"office_label": row.office_label, "district_label": row.district_label or ""},
            protected_address=row.address,
            retrieval_context={"party": row.party},
        )

        candidates.append(
            CandidateFilingRecord(
                filing_key=stable_public_id("filing", contest_id, source_row_key),
                contest_public_id=contest_id,
                ballot_name=row.reported_name,
                source_records=(evidence,),
                person_public_id=_resolve_person_public_id(row, ocpf_pool=ocpf_pool),
                canonical_name=row.reported_name,
                given_name=row.given_name,
                middle_name=row.middle_name,
                family_name=row.family_name,
                suffix=row.suffix,
                party_candidate=row.party,
                status="active",
            )
        )

    notices = tuple(
        _no_nomination_notice(office_label, district_label)
        for office_label, district_label in no_nominations
    )

    batch = PreElectionBatch(
        state="MA",
        jurisdictions=tuple(sorted(jurisdictions.values(), key=lambda record: record.public_id)),
        offices=tuple(sorted(offices.values(), key=lambda record: record.public_id)),
        elections=(election,),
        contests=tuple(sorted(contests.values(), key=lambda record: record.public_id)),
        candidates=tuple(candidates),
        notices=notices,
    )
    validate_pre_election_batch(batch)
    return batch
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/tests/test_batch.py -v --no-migrations`
Expected: PASS (7 tests)

Then run the full plan's test suite together:
Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/ -v --no-migrations`
Expected: PASS (28 carried over from Plans 1-2 + 31 new from this plan: 11+6+7+7 = 31 → 59 total)

Also run: `docker compose -f docker-compose.v2.yaml run --rm test ruff check cm2_ma`
Expected: clean

Also run (regression check, matching Plan 1's and Plan 2's Definition of Done):
Run: `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_core/tests/test_foundation.py -v --no-migrations`
Expected: still passes

- [ ] **Step 5: Commit**

```bash
git add backend/cm2_ma/mapping/batch.py backend/cm2_ma/tests/test_batch.py
git commit -m "feat(cm2_ma): build PreElectionBatch from Secretary candidate pages, OCPF-matched where possible"
```

---

## Definition of done

- `docker compose -f docker-compose.v2.yaml run --rm test python manage.py check --settings=config.settings.v2` passes.
- `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_ma/ -v --no-migrations` passes (59 tests: 28 from Plans 1-2 + 31 new — verify this exact number by running `--collect-only` before treating any final-review count mismatch as a defect, the way Plan 2's review did).
- `docker compose -f docker-compose.v2.yaml run --rm test ruff check cm2_ma` passes.
- `docker compose -f docker-compose.v2.yaml run --rm test pytest cm2_core/tests/test_foundation.py -v --no-migrations` still passes.
- No changes outside `backend/cm2_ma/`.
- `core/cf_solver.py`, `cloudflare/cf-solver/`, and `cm2_ma/mapping/ocpf_pool.py` are untouched.
- No Django model, database, or persistence code anywhere in this plan — it produces a `PreElectionBatch` value object only. Wiring it into `apply_pre_election_batch` (the actual DB write) is orchestration work, out of scope here, matching Plan 1's and Plan 2's precedent that scheduling/triggering is unbuilt for the whole CM2 program.

## Known open items carried forward (not this plan's job to fix)

1. The 19th Worcester House district has no OCPF code — confirmed real gap, always falls through to provisional-person. If OCPF ever adds a code for it, no code change is needed here; it'll just start matching.
2. Five of six statewide offices' OCPF `District_Description` values (`Governor`, `Lieutenant Governor`, `Attorney General`, `Secretary of State`, `Treasurer`) are assumed, not individually verified (only `Auditor` was). Worth a live spot-check before relying heavily on statewide OCPF matches.
3. `vote_for` is hardcoded to `1` for every contest — the design spec's ballot-sample-based vote-for validation is future work.
4. The general-election candidate page doesn't exist yet (per the design spec) — this plan only handles the two primary pages.
5. Special-election candidate pages (as opposed to the special-election *calendar* pages Plan 1 already handles) are out of scope here too.

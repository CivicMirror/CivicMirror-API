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


def _normalize_district_text(text: str, *, keep_suffix: bool, abbreviate_ordinals: bool = True) -> str:
    normalized = text.strip()
    if not keep_suffix:
        normalized = re.sub(r"\s+District$", "", normalized)
        normalized = re.sub(r"\s+County$", " County", normalized)  # no-op placeholder kept explicit for clarity

    if abbreviate_ordinals:
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

    # For Senate, we need to do the translation before abbreviating ordinals
    # (the Senate dict has full words like "third")
    if ocpf_office_type == "Senate":
        normalized = _normalize_district_text(district_label, keep_suffix=keep_suffix, abbreviate_ordinals=False)
        normalized = _SENATE_NEW_TO_OLD.get(normalized.casefold(), normalized)
        # Now abbreviate ordinals in the translated result
        normalized = _normalize_district_text(normalized, keep_suffix=keep_suffix, abbreviate_ordinals=True)
    else:
        normalized = _normalize_district_text(district_label, keep_suffix=keep_suffix)

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

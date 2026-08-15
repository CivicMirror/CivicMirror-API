import re

from .identity import normalize_identity_part

_PARTY_SUFFIX_RE = re.compile(r"\s*\(([A-Z]{2,5})\)$")
_UNEXPIRED_SUFFIX_RE = re.compile(r"\s*\(UNEXPIRED\)$")
_WRITE_IN_MARKER_RE = re.compile(r"\(\s*WRITE-IN\s*\)|\bWRITE-IN\b|\(\s*MISCELLANEOUS\s*\)", re.IGNORECASE)


def split_contest_label(raw_label: str) -> tuple[str, str, bool]:
    label = " ".join((raw_label or "").strip().upper().split())

    party = ""
    party_match = _PARTY_SUFFIX_RE.search(label)
    if party_match:
        party = party_match.group(1)
        label = label[: party_match.start()].strip()

    is_unexpired = False
    if _UNEXPIRED_SUFFIX_RE.search(label):
        is_unexpired = True
        label = _UNEXPIRED_SUFFIX_RE.sub("", label).strip()

    return label, party, is_unexpired


def classify_choice(source_label: str) -> str:
    if not _WRITE_IN_MARKER_RE.search(source_label or ""):
        return "candidate"
    remainder = _WRITE_IN_MARKER_RE.sub("", source_label).strip()
    if normalize_identity_part(remainder) in {"", "miscellaneous"}:
        return "write_in_aggregate"
    return "named_write_in"


def normalized_choice_label(source_label: str, choice_type: str) -> str:
    if choice_type == "write_in_aggregate":
        return "write-in"
    remainder = _WRITE_IN_MARKER_RE.sub("", source_label or "").strip()
    return normalize_identity_part(remainder)

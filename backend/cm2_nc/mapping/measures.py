import re

_MEASURE_WORDS = (
    "referendum",
    "referenda",
    "bond",
    "bonds",
    "amendment",
    "measure",
    "proposition",
    "question",
    "initiative",
    "levy",
    "ordinance",
    "resolution",
)
_MEASURE_RE = re.compile(rf"\b(?:{'|'.join(_MEASURE_WORDS)})\b", re.IGNORECASE)


def is_measure_contest(contest_name: str) -> bool:
    normalized = " ".join((contest_name or "").split())
    return bool(_MEASURE_RE.search(normalized))

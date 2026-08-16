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


MEASURE_CHOICE_LABELS = frozenset({"for", "against", "yes", "no"})


def is_measure_contest(
    contest_name: str,
    *,
    choice_labels: frozenset[str] | set[str] | None = None,
) -> bool:
    normalized = " ".join((contest_name or "").split())
    if _MEASURE_RE.search(normalized):
        return True
    if choice_labels:
        return set(choice_labels) <= MEASURE_CHOICE_LABELS
    return False

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from difflib import SequenceMatcher

from django.db.models import Q

from cm2_elections.models import Person

from .models import IdentityReviewCase, IdentityReviewSuggestion

SUGGESTION_SCORE_FLOOR = 0.72
MAX_SUGGESTIONS = 5


def normalize_name_for_matching(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return " ".join(normalized.casefold().split())


@dataclass
class PersonMatchCandidate:
    person: Person
    score: float
    supporting_evidence: dict = field(default_factory=dict)
    conflicting_evidence: dict = field(default_factory=dict)


def find_person_match_candidates(
    *,
    canonical_name: str,
    family_name: str,
    exclude_person_id: uuid.UUID,
    limit: int = MAX_SUGGESTIONS,
    score_floor: float = SUGGESTION_SCORE_FLOOR,
) -> list[PersonMatchCandidate]:
    normalized_target = normalize_name_for_matching(canonical_name)
    if not normalized_target:
        return []

    candidates_qs = Person.objects.exclude(pk=exclude_person_id).exclude(
        identity_state=Person.IdentityState.MERGED
    )
    normalized_family = normalize_name_for_matching(family_name)
    if normalized_family:
        candidates_qs = candidates_qs.filter(
            Q(family_name__istartswith=normalized_family[0]) | Q(family_name="")
        )

    matcher = SequenceMatcher(a=normalized_target)
    scored: list[PersonMatchCandidate] = []
    for existing in candidates_qs.iterator():
        normalized_existing = normalize_name_for_matching(existing.canonical_name)
        matcher.set_seq2(normalized_existing)
        if matcher.quick_ratio() < score_floor:
            continue
        score = matcher.ratio()
        if score < score_floor:
            continue
        scored.append(
            PersonMatchCandidate(
                person=existing,
                score=round(score, 4),
                supporting_evidence={
                    "matched_name": existing.canonical_name,
                    "name_similarity": round(score, 4),
                },
            )
        )

    scored.sort(key=lambda candidate: candidate.score, reverse=True)
    return scored[:limit]


def generate_suggestions_for_case(
    review_case: IdentityReviewCase,
    candidates: list[PersonMatchCandidate],
) -> list[IdentityReviewSuggestion]:
    suggestions = [
        IdentityReviewSuggestion(
            review_case=review_case,
            suggested_person=candidate.person,
            rank=rank,
            score=Decimal(str(candidate.score)),
            supporting_evidence=candidate.supporting_evidence,
            conflicting_evidence=candidate.conflicting_evidence,
            uses_private_evidence=False,
        )
        for rank, candidate in enumerate(candidates, start=1)
    ]
    return IdentityReviewSuggestion.objects.bulk_create(suggestions)

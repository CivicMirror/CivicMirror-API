from collections import defaultdict
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from .contracts import AggregatedResultChoice, ContractValidationError, PrecinctResultObservation

_PERCENTAGE_QUANTUM = Decimal("0.0001")


def aggregate_precinct_observations(
    observations: Iterable[PrecinctResultObservation],
) -> tuple[AggregatedResultChoice, ...]:
    seen_observation_keys: set[str] = set()
    grouped: dict[tuple[str, str], dict] = {}
    contest_totals: dict[str, int] = defaultdict(int)

    for observation in observations:
        if not observation.source_observation_key:
            raise ContractValidationError("result observation key must be non-empty")
        if observation.source_observation_key in seen_observation_keys:
            raise ContractValidationError("duplicate result observation key")
        seen_observation_keys.add(observation.source_observation_key)
        if observation.vote_total < 0:
            raise ContractValidationError("result observation vote total cannot be negative")

        group_key = (observation.contest_public_id, observation.source_choice_key)
        metadata = (
            observation.source_label,
            observation.normalized_label,
            observation.choice_type,
            observation.choice_party,
        )
        group = grouped.get(group_key)
        if group is None:
            group = {
                "metadata": metadata,
                "vote_total": 0,
                "observation_keys": [],
            }
            grouped[group_key] = group
        elif group["metadata"] != metadata:
            raise ContractValidationError("conflicting result choice metadata")

        group["vote_total"] += observation.vote_total
        group["observation_keys"].append(observation.source_observation_key)
        contest_totals[observation.contest_public_id] += observation.vote_total

    result: list[AggregatedResultChoice] = []
    for (contest_public_id, source_choice_key), group in sorted(grouped.items()):
        source_label, normalized_label, choice_type, choice_party = group["metadata"]
        denominator = contest_totals[contest_public_id]
        percentage = (
            (Decimal(group["vote_total"]) * Decimal("100") / Decimal(denominator)).quantize(
                _PERCENTAGE_QUANTUM,
                rounding=ROUND_HALF_UP,
            )
            if denominator
            else Decimal("0.0000")
        )
        observation_keys = tuple(sorted(group["observation_keys"]))
        result.append(
            AggregatedResultChoice(
                contest_public_id=contest_public_id,
                source_choice_key=source_choice_key,
                source_label=source_label,
                normalized_label=normalized_label,
                choice_type=choice_type,
                vote_total=group["vote_total"],
                percentage=percentage,
                observation_count=len(observation_keys),
                observation_keys=observation_keys,
                choice_party=choice_party,
            )
        )

    return tuple(result)

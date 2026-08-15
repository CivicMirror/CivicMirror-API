from difflib import SequenceMatcher

from django.db import transaction
from django.utils import timezone

from cm2_core.models import SourceArtifact
from cm2_elections.models import Candidacy, Contest, Person
from cm2_results.models import ContestResult, ResultChoice
from cm2_review.matching import find_person_match_candidates, generate_suggestions_for_case, normalize_name_for_matching
from cm2_review.models import IdentityReviewCase
from cm2_review.workflow import create_review_case

from . import entities
from .aggregation import aggregate_precinct_observations
from .contracts import AggregatedResultChoice, ContractValidationError, PostElectionBatch, validate_post_election_batch
from .models import ReconciliationReport, SyncLog

_COUNT_KEYS = (
    "jurisdictions_created",
    "jurisdictions_updated",
    "offices_created",
    "offices_updated",
    "contests_created",
    "contests_updated",
    "contest_results_created",
    "contest_results_updated",
    "result_choices_created",
    "result_choices_updated",
    "people_created",
    "candidacies_created",
    "review_cases_created",
)

_MATCH_SCORE_FLOOR = 0.72


def _new_counts() -> dict[str, int]:
    return {key: 0 for key in _COUNT_KEYS}


def _empty_details() -> dict:
    categories = ("jurisdictions", "offices", "contests")
    return {
        "created": {category: [] for category in categories},
        "updated": {category: [] for category in categories},
        "result_only_contests": [],
        "unmatched_choices": [],
        "review_cases": [],
        "notices": [],
    }


def _safe_error_summary(exc: Exception) -> str:
    if isinstance(exc, ContractValidationError):
        return "ContractValidationError: batch validation failed"
    return f"{type(exc).__name__}: persistence failed"


def _resolve_candidacy(*, contest: Contest, normalized_label: str) -> tuple[Candidacy | None, str, list[dict]]:
    candidacies = list(Candidacy.objects.filter(contest=contest).select_related("person"))
    exact = [
        candidacy for candidacy in candidacies
        if normalize_name_for_matching(candidacy.ballot_name) == normalized_label
    ]
    if len(exact) == 1:
        return exact[0], ResultChoice.ResolutionStatus.MATCHED, []
    if len(exact) > 1:
        return None, ResultChoice.ResolutionStatus.AMBIGUOUS, [
            {"candidacy_public_id": candidacy.public_id, "ballot_name": candidacy.ballot_name} for candidacy in exact
        ]

    matcher = SequenceMatcher(a=normalized_label)
    fuzzy = []
    for candidacy in candidacies:
        matcher.set_seq2(normalize_name_for_matching(candidacy.ballot_name))
        score = matcher.ratio()
        if score >= _MATCH_SCORE_FLOOR:
            fuzzy.append({"candidacy_public_id": candidacy.public_id, "ballot_name": candidacy.ballot_name, "score": round(score, 4)})
    if fuzzy:
        return None, ResultChoice.ResolutionStatus.UNRESOLVED, fuzzy
    return None, "", []


def _create_provisional_candidacy(
    *,
    artifact: SourceArtifact,
    contest: Contest,
    choice: AggregatedResultChoice,
) -> tuple[Candidacy, IdentityReviewCase | None]:
    person = Person.objects.create(
        canonical_name=choice.source_label,
        identity_state=Person.IdentityState.PROVISIONAL,
        source_artifact=artifact,
        source_key=choice.source_choice_key,
    )
    candidacy = Candidacy.objects.create(
        person=person,
        contest=contest,
        ballot_name=choice.source_label,
        party_candidate=choice.choice_party,
        status=Candidacy.Status.PROVISIONAL,
        source_artifact=artifact,
        source_key=choice.source_choice_key,
    )
    match_candidates = find_person_match_candidates(
        canonical_name=person.canonical_name,
        family_name="",
        exclude_person_id=person.id,
    )
    case_type = (
        IdentityReviewCase.CaseType.FUZZY_PERSON_MATCH if match_candidates else IdentityReviewCase.CaseType.PERSON_IDENTITY
    )
    review_case, created = create_review_case(
        deduplication_key=f"new-result-person:{artifact.public_id}:{choice.source_choice_key}",
        defaults={
            "case_type": case_type,
            "provisional_person": person,
            "supporting_evidence": {"source_system": artifact.source_system, "source_choice_key": choice.source_choice_key},
        },
    )
    if created and match_candidates:
        generate_suggestions_for_case(review_case, match_candidates)
    return candidacy, review_case if created else None


def _persist_contest_result(
    *,
    artifact: SourceArtifact,
    contest: Contest,
    choices: tuple[AggregatedResultChoice, ...],
    counts: dict[str, int],
    details: dict,
) -> None:
    total_votes = sum(choice.vote_total for choice in choices)
    result, created = ContestResult.objects.get_or_create(
        contest=contest,
        defaults={
            "status": ContestResult.Status.UNOFFICIAL,
            "source_artifact": artifact,
            "total_votes": total_votes,
            "reported_at": timezone.now(),
        },
    )
    if created:
        counts["contest_results_created"] += 1
    else:
        update_fields = ["total_votes", "source_artifact", "reported_at", "updated_at"]
        result.total_votes = total_votes
        result.source_artifact = artifact
        result.reported_at = timezone.now()
        if result.status == ContestResult.Status.PENDING:
            result.status = ContestResult.Status.UNOFFICIAL
            update_fields.append("status")
        result.save(update_fields=update_fields)
        counts["contest_results_updated"] += 1

    for choice in choices:
        candidacy = None
        review_supporting_evidence: list[dict] = []
        if choice.choice_type == "write_in_aggregate":
            resolution_status = ResultChoice.ResolutionStatus.NOT_APPLICABLE
        elif choice.choice_type == "named_write_in":
            resolution_status = ResultChoice.ResolutionStatus.UNRESOLVED
        else:
            candidacy, resolution_status, review_supporting_evidence = _resolve_candidacy(
                contest=contest,
                normalized_label=choice.normalized_label,
            )
            if not resolution_status:
                candidacy, _ = _create_provisional_candidacy(artifact=artifact, contest=contest, choice=choice)
                resolution_status = ResultChoice.ResolutionStatus.PROVISIONAL
                counts["people_created"] += 1
                counts["candidacies_created"] += 1
                counts["review_cases_created"] += 1

        values = {
            "source_label": choice.source_label,
            "normalized_label": choice.normalized_label,
            "choice_type": choice.choice_type,
            "resolution_status": resolution_status,
            "candidacy": candidacy,
            "vote_total": choice.vote_total,
            "percentage": choice.percentage,
            "source_artifact": artifact,
            "observation_lineage": list(choice.observation_keys),
        }
        result_choice, choice_created = ResultChoice.objects.get_or_create(
            contest_result=result,
            source_choice_key=choice.source_choice_key,
            defaults=values,
        )
        if choice_created:
            counts["result_choices_created"] += 1
        else:
            for field_name, value in values.items():
                setattr(result_choice, field_name, value)
            result_choice.save(update_fields=[*values.keys(), "updated_at"])
            counts["result_choices_updated"] += 1

        if resolution_status == ResultChoice.ResolutionStatus.UNRESOLVED and choice.choice_type != "candidate":
            review_case, created = create_review_case(
                deduplication_key=f"unresolved-choice:{result_choice.public_id}",
                defaults={
                    "case_type": IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE,
                    "result_choice": result_choice,
                    "supporting_evidence": {"source_label": choice.source_label},
                },
            )
            if created:
                counts["review_cases_created"] += 1
            details["review_cases"].append(review_case.public_id)
        elif resolution_status in (ResultChoice.ResolutionStatus.UNRESOLVED, ResultChoice.ResolutionStatus.AMBIGUOUS):
            review_case, created = create_review_case(
                deduplication_key=f"unresolved-choice:{result_choice.public_id}",
                defaults={
                    "case_type": IdentityReviewCase.CaseType.UNRESOLVED_RESULT_CHOICE,
                    "result_choice": result_choice,
                    "supporting_evidence": {"source_label": choice.source_label, "candidates": review_supporting_evidence},
                },
            )
            if created:
                counts["review_cases_created"] += 1
            details["review_cases"].append(review_case.public_id)
            details["unmatched_choices"].append(result_choice.public_id)


def _persist_results_batch(
    *,
    artifact: SourceArtifact,
    batch: PostElectionBatch,
    sync_log: SyncLog,
) -> ReconciliationReport:
    counts = _new_counts()
    details = _empty_details()
    for notice in batch.notices:
        count_key = f"notices_{notice.code}"
        counts[count_key] = counts.get(count_key, 0) + 1
        details["notices"].append(
            {"code": notice.code, "subject_type": notice.subject_type, "subject_public_id": notice.subject_public_id}
        )

    jurisdictions = entities.persist_jurisdictions(
        artifact=artifact, records=batch.new_jurisdictions, counts=counts, details=details
    )
    offices = entities.persist_offices(
        artifact=artifact, records=batch.new_offices, jurisdictions=jurisdictions, counts=counts, details=details
    )
    existing_election_ids = {contest.election_public_id for contest in batch.new_contests}
    from cm2_elections.models import Election

    elections = {
        election.public_id: election
        for election in Election.objects.filter(public_id__in=existing_election_ids)
    }
    if len(elections) != len(existing_election_ids):
        raise ContractValidationError("post-election batch references an election that does not exist")
    contests = entities.persist_contests(
        artifact=artifact, records=batch.new_contests, elections=elections, offices=offices, counts=counts, details=details
    )

    observations_by_contest: dict[str, list] = {}
    for observation in batch.observations:
        observations_by_contest.setdefault(observation.contest_public_id, []).append(observation)

    for contest_public_id, observations in observations_by_contest.items():
        contest = contests.get(contest_public_id) or Contest.objects.filter(public_id=contest_public_id).first()
        if contest is None:
            raise ContractValidationError("result observation references an unknown contest")
        aggregated = aggregate_precinct_observations(observations)
        _persist_contest_result(artifact=artifact, contest=contest, choices=aggregated, counts=counts, details=details)

    completed_at = timezone.now()
    sync_log.status = SyncLog.Status.SUCCESS
    sync_log.completed_at = completed_at
    sync_log.aggregate_counts = counts
    sync_log.error_summary = ""
    sync_log.save(update_fields=["status", "completed_at", "aggregate_counts", "error_summary", "updated_at"])
    return ReconciliationReport.objects.create(sync_log=sync_log, source_artifact=artifact, details=details)


def apply_post_election_batch(*, artifact: SourceArtifact, batch: PostElectionBatch) -> ReconciliationReport:
    run_key = f"results:{artifact.public_id}"
    sync_log, _ = SyncLog.objects.get_or_create(
        run_key=run_key,
        defaults={
            "state": batch.state,
            "source_system": artifact.source_system,
            "capability": SyncLog.Capability.RESULTS,
            "source_artifact": artifact,
            "started_at": timezone.now(),
        },
    )
    if sync_log.status == SyncLog.Status.SUCCESS:
        try:
            return sync_log.report
        except ReconciliationReport.DoesNotExist:
            pass

    SyncLog.objects.filter(pk=sync_log.pk).update(
        state=batch.state,
        source_system=artifact.source_system,
        capability=SyncLog.Capability.RESULTS,
        status=SyncLog.Status.STARTED,
        source_artifact=artifact,
        started_at=timezone.now(),
        completed_at=None,
        aggregate_counts={},
        error_summary="",
    )
    sync_log.refresh_from_db()

    try:
        validate_post_election_batch(batch)
        with transaction.atomic():
            return _persist_results_batch(artifact=artifact, batch=batch, sync_log=sync_log)
    except Exception as exc:
        SyncLog.objects.filter(pk=sync_log.pk).update(
            status=SyncLog.Status.FAILED,
            completed_at=timezone.now(),
            aggregate_counts={},
            error_summary=_safe_error_summary(exc),
        )
        raise

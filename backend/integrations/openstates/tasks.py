from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from integrations.orchestrator.candidate_matcher import CandidateMatcher
from integrations.orchestrator.exceptions import AmbiguousMatchError
from integrations.orchestrator.source_store import SourceRecordStore
from ops.models import SyncLog

from .client import OpenStatesClient, OpenStatesError, OpenStatesForbiddenError, OpenStatesRateLimitError
from .mappers import map_person

logger = logging.getLogger(__name__)

US_STATES = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA',
    'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT',
    'VA', 'WA', 'WV', 'WI', 'WY',
]


def _save_source_links(source_record, *, candidate=None):
    if getattr(source_record, 'linked_candidate_id', None) != getattr(candidate, 'pk', None):
        source_record.linked_candidate = candidate
        source_record.save(update_fields=['linked_candidate'])


@shared_task(bind=True, max_retries=3)
def sync_openstates_legislators(self, state: str):
    state = (state or '').upper()
    sync_log = SyncLog.objects.create(
        source='openstates',
        task_name='sync_openstates_legislators',
        address_label=state,
        status=SyncLog.Status.STARTED,
    )
    store = SourceRecordStore()
    matcher = CandidateMatcher()
    client = OpenStatesClient()
    updated_count = 0
    created_count = 0
    skipped_count = 0
    warning_count = 0
    last_warning = ''

    try:
        for raw_person in client.list_people_all_pages(state):
            person_id = str(raw_person.get('id') or '').strip()
            if not person_id:
                skipped_count += 1
                continue

            source_record, changed = store.upsert('openstates', person_id, raw_person)
            # An unchanged payload only means it's safe to skip re-fetching —
            # it doesn't mean the last attempt found a match. Without a linked
            # candidate, the payload hasn't proven it can enrich anything yet,
            # so keep retrying (e.g. the candidate for this cycle may not have
            # existed on the last run).
            if not changed and source_record.linked_candidate_id:
                skipped_count += 1
                continue

            mapped = map_person(raw_person, state=state)
            enrichment_payload = dict(mapped)
            enrichment_payload['name'] = mapped.get('display_name', '')

            # Resolve races explicitly (state+chamber+district) and enrich
            # each individually, rather than matching cross-race by
            # state+chamber alone: a candidate on both a primary Race and a
            # general Race for the same seat (see ma_sos
            # mappers.contest_variant_key) would otherwise always collide as
            # "ambiguous" under name/last-name cross-race matching, since
            # both rows share the same name, state, chamber, and district.
            # Enriching within each resolved race individually — same
            # pattern as ma_sos.tasks.sync_ocpf_ma_candidates — lets every
            # row get updated. Falls back to enrich_or_create's cross-race
            # matching (and its single-race create path) when no races
            # resolve this way, e.g. executive offices or states/offices
            # find_races_for_legislator doesn't cover.
            races = matcher.find_races_for_legislator(
                enrichment_payload.get('state', ''),
                enrichment_payload.get('chamber', ''),
                enrichment_payload.get('district', ''),
            )

            linked_candidate = None
            if races:
                matched_any = False
                for race in races:
                    try:
                        candidate, action = matcher.enrich(
                            race=race, source='openstates',
                            external_id=person_id, enrichment_payload=enrichment_payload,
                        )
                    except AmbiguousMatchError as exc:
                        warning_count += 1
                        last_warning = str(exc)
                        continue

                    if action == 'enriched':
                        matched_any = True
                        updated_count += 1
                        linked_candidate = candidate
                    elif action == 'skipped':
                        matched_any = True
                        linked_candidate = candidate
                    elif action == 'ambiguous':
                        warning_count += 1
                        last_warning = f'Ambiguous candidate match for openstates:{person_id} in race={race.pk}'

                    if action in ('enriched', 'skipped') and candidate is not None:
                        sources = list(candidate.contributing_sources or [])
                        if 'openstates' not in sources:
                            sources.append('openstates')
                            candidate.contributing_sources = sources
                            candidate.save(update_fields=['contributing_sources'])

                if not matched_any:
                    skipped_count += 1
            else:
                try:
                    candidate, action = matcher.enrich_or_create(
                        race=None,
                        source='openstates',
                        external_id=person_id,
                        enrichment_payload=enrichment_payload,
                    )
                except AmbiguousMatchError as exc:
                    warning_count += 1
                    last_warning = str(exc)
                    skipped_count += 1
                    continue

                if action == 'enriched':
                    updated_count += 1
                    linked_candidate = candidate
                elif action == 'created':
                    created_count += 1
                    linked_candidate = candidate
                elif action == 'skipped':
                    skipped_count += 1
                    linked_candidate = candidate
                else:
                    skipped_count += 1
                    if action == 'ambiguous':
                        warning_count += 1
                        last_warning = f'Ambiguous candidate match for openstates:{person_id}'

                if action in ('enriched', 'created', 'skipped') and candidate is not None:
                    sources = list(candidate.contributing_sources or [])
                    if 'openstates' not in sources:
                        sources.append('openstates')
                        candidate.contributing_sources = sources
                        candidate.save(update_fields=['contributing_sources'])

            if linked_candidate is not None:
                _save_source_links(source_record, candidate=linked_candidate)

        sync_log.records_updated = updated_count
        sync_log.records_skipped = skipped_count
        sync_log.error_count = warning_count
        sync_log.last_error = last_warning
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS if warning_count else SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(
            update_fields=['records_updated', 'records_skipped', 'error_count', 'last_error', 'status', 'completed_at']
        )
        return {'updated': updated_count, 'created': created_count, 'skipped': skipped_count, 'warnings': warning_count, 'state': state}
    except OpenStatesForbiddenError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=['error_count', 'last_error', 'status', 'completed_at'])
        raise
    except OpenStatesRateLimitError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=['error_count', 'last_error', 'status', 'completed_at'])
        raise self.retry(exc=exc, countdown=600)
    except OpenStatesError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=['error_count', 'last_error', 'status', 'completed_at'])
        raise self.retry(exc=exc, countdown=300)
    except Exception as exc:
        logger.exception('Open States sync failed for state=%s', state)
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=['error_count', 'last_error', 'status', 'completed_at'])
        raise


@shared_task
def sync_openstates_all_states():
    for index, state in enumerate(US_STATES):
        sync_openstates_legislators.apply_async(args=[state], countdown=index * 60)

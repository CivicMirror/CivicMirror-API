from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from integrations.orchestrator.candidate_matcher import CandidateMatcher
from integrations.orchestrator.exceptions import AmbiguousMatchError
from integrations.orchestrator.source_store import SourceRecordStore
from ops.models import SyncLog

from .client import OpenStatesClient, OpenStatesForbiddenError, OpenStatesRateLimitError
from .mappers import map_person

logger = logging.getLogger(__name__)

US_STATES = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA',
    'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT',
    'VA', 'WA', 'WV', 'WI', 'WY',
]


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

            _, changed = store.upsert('openstates', person_id, raw_person)
            if not changed:
                skipped_count += 1
                continue

            mapped = map_person(raw_person)
            enrichment_payload = dict(mapped)
            enrichment_payload['name'] = mapped.get('display_name', '')

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
            elif action == 'created':
                created_count += 1
            else:
                skipped_count += 1
                if action == 'ambiguous':
                    warning_count += 1
                    last_warning = f'Ambiguous candidate match for openstates:{person_id}'
                candidate = None

            if action in ('enriched', 'created') and candidate is not None:
                sources = list(candidate.contributing_sources or [])
                if 'openstates' not in sources:
                    sources.append('openstates')
                    candidate.contributing_sources = sources
                    candidate.save(update_fields=['contributing_sources'])

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

"""
Celery tasks for the SC ENR integration.

Task flow:
  poll_sc_enr_elections  (scheduled during election season)
    → discovers active elections from elections.json
    → upserts ENRElection records (never deletes — marks is_active=False for missing entries)
    → resolves /web.XXXXXX/ URLs for new/unresolved entries
    → links state-level entries to Election records by date
    → copies enr_resolved_url → Election.results_url for auto-linked entries

  sync_sc_enr_results  (triggered by poll or scheduled during election window)
    → finds active ENRElections with a linked Election record
    → delegates to ClarityAdapter (which reads Election.results_url)
"""
import logging
from datetime import date as _date

from celery import shared_task
from django.utils import timezone

from ops.models import SyncLog

from .client import ENRClient
from .exceptions import SCEnrError, SCEnrRetryableError
from .mappers import attempt_election_link, map_enr_election
from .models import ENRElection

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def poll_sc_enr_elections(self):
    """
    Stage 1: Discover active SC ENR elections from elections.json.

    - Upserts ENRElection records for every entry in the feed.
    - Marks entries no longer in the feed as is_active=False (never deletes).
    - Resolves /web.XXXXXX/ URLs for new entries or entries with empty resolved URL.
    - Links state-level entries to existing Election records by date.
    - Copies enr_resolved_url → Election.results_url for auto-linked entries.
    """
    sync_log = SyncLog.objects.create(
        source="sc_enr",
        task_name="poll_sc_enr_elections",
        status=SyncLog.Status.STARTED,
    )
    client = ENRClient()
    created_count = updated_count = linked_count = resolved_count = 0

    try:
        entries = client.get_elections()
        logger.info("sc_enr.poll_elections feed_entries=%d", len(entries))

        seen_keys: set[tuple[int, str | None]] = set()
        now = timezone.now()

        for entry in entries:
            try:
                fields = map_enr_election(entry)
            except (ValueError, KeyError) as exc:
                logger.warning("sc_enr.poll_elections.bad_entry entry=%r error=%s", entry, exc)
                continue

            eid: int = fields["eid"]
            county: str | None = fields["county"]
            seen_keys.add((eid, county))

            # Upsert the ENRElection record.
            if county is not None:
                lookup = {"eid": eid, "county": county}
            else:
                lookup = {"eid": eid, "county__isnull": True}

            existing = ENRElection.objects.filter(**lookup).first()
            if existing:
                # Update mutable fields; preserve enr_resolved_url, election FK, link_confidence.
                changed = False
                for field in ("election_name", "election_date", "scope", "enr_base_url"):
                    if getattr(existing, field) != fields[field]:
                        setattr(existing, field, fields[field])
                        changed = True
                if not existing.is_active:
                    existing.is_active = True
                    changed = True
                existing.last_seen_at = now
                update_fields = ["last_seen_at"]
                if changed:
                    update_fields += ["election_name", "election_date", "scope", "enr_base_url", "is_active"]
                existing.save(update_fields=update_fields)
                enr_obj = existing
                updated_count += 1
            else:
                enr_obj = ENRElection.objects.create(
                    **fields,
                    enr_resolved_url="",
                    is_active=True,
                    last_seen_at=now,
                )
                created_count += 1

            # Resolve the /web.XXXXXX/ URL if not yet known.
            if not enr_obj.enr_resolved_url:
                try:
                    resolved = client.resolve_url(eid, county)
                    enr_obj.enr_resolved_url = resolved
                    enr_obj.save(update_fields=["enr_resolved_url"])
                    resolved_count += 1
                    logger.info("sc_enr.resolved eid=%d county=%s url=%s", eid, county, resolved)
                except SCEnrRetryableError as exc:
                    logger.warning("sc_enr.resolve_url.failed eid=%d error=%s", eid, exc)
                except SCEnrError as exc:
                    logger.warning("sc_enr.resolve_url.error eid=%d error=%s", eid, exc)

            # Link state-level entries to Election records.
            if (
                enr_obj.scope == ENRElection.Scope.STATE
                and enr_obj.enr_resolved_url
                and enr_obj.link_confidence != ENRElection.LinkConfidence.MANUAL
            ):
                election_obj, confidence = attempt_election_link(enr_obj)

                save_fields = []
                if enr_obj.link_confidence != confidence:
                    enr_obj.link_confidence = confidence
                    save_fields.append("link_confidence")

                if election_obj and enr_obj.election_id != election_obj.pk:
                    enr_obj.election = election_obj
                    save_fields.append("election")
                    linked_count += 1

                    # Route results_url write through the aggregation ingest service
                    # so precedence, contributing_sources, and ElectionSourceLink are
                    # maintained consistently with other Phase-2 adapters.
                    if enr_obj.enr_resolved_url:
                        try:
                            from aggregation import ingest
                            ingest.ingest_election(
                                source="sc_enr",
                                source_id=f"sc_enr_{enr_obj.eid}",
                                identity={
                                    "state":              election_obj.state,
                                    "election_type":      election_obj.election_type,
                                    "election_date":      election_obj.election_date,
                                    "jurisdiction_level": election_obj.jurisdiction_level,
                                },
                                fields={"results_url": enr_obj.enr_resolved_url},
                            )
                            logger.info(
                                "sc_enr.results_url_set election_pk=%d url=%s",
                                election_obj.pk,
                                enr_obj.enr_resolved_url,
                            )
                        except Exception as exc:
                            logger.warning(
                                "sc_enr.results_url_ingest_failed eid=%d error=%s",
                                enr_obj.eid, exc,
                            )

                if save_fields:
                    enr_obj.save(update_fields=save_fields)

        # Mark entries no longer present in the feed as inactive.
        # Build the full set of active PKs to avoid N+1 queries.
        all_active = ENRElection.objects.filter(is_active=True)
        stale_pks = []
        for rec in all_active:
            key = (rec.eid, rec.county)
            if key not in seen_keys:
                stale_pks.append(rec.pk)

        if stale_pks:
            stale_count = ENRElection.objects.filter(pk__in=stale_pks).update(
                is_active=False
            )
            logger.info("sc_enr.poll_elections.marked_inactive count=%d", stale_count)

        sync_log.records_created = created_count
        sync_log.records_updated = updated_count
        sync_log.notes = (
            f"feed={len(entries)} created={created_count} updated={updated_count} "
            f"resolved={resolved_count} linked={linked_count}"
        )
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=[
            "records_created", "records_updated", "notes", "status", "completed_at",
        ])
        return {
            "feed": len(entries),
            "created": created_count,
            "updated": updated_count,
            "resolved": resolved_count,
            "linked": linked_count,
        }

    except SCEnrRetryableError as exc:
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.COMPLETED_WITH_WARNINGS
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise self.retry(exc=exc)

    except Exception as exc:
        logger.exception("sc_enr.poll_elections.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_sc_enr_results(self):
    """
    Stage 2: Fetch and ingest results for active linked SC ENR elections.

    Delegates to ClarityAdapter via the existing results ingestion path
    (results.tasks.ingest_official_results). Only processes ENRElections that:
      - are is_active=True
      - have a linked Election FK (election_id is not null)
      - are state-level (scope="state") — state detailxml.zip includes county subtotals

    County-level ENRElections are stored for future precinct-level ingestion
    but are not fetched here.
    """
    from results.tasks import ingest_official_results

    sync_log = SyncLog.objects.create(
        source="sc_enr",
        task_name="sync_sc_enr_results",
        status=SyncLog.Status.STARTED,
    )

    try:
        active_linked = list(
            ENRElection.objects.filter(
                is_active=True,
                scope=ENRElection.Scope.STATE,
                election__isnull=False,
            ).select_related("election")
        )

        logger.info("sc_enr.sync_results active_linked=%d", len(active_linked))

        queued_count = 0
        for idx, enr_obj in enumerate(active_linked):
            if not enr_obj.enr_resolved_url:
                logger.warning(
                    "sc_enr.sync_results.no_resolved_url eid=%d election_pk=%d — skipping",
                    enr_obj.eid,
                    enr_obj.election_id,
                )
                continue

            # Stagger at 5-second intervals to avoid burst on Clarity ENR.
            ingest_official_results.apply_async(
                args=["SC", enr_obj.election_id],
                countdown=idx * 5,
            )
            queued_count += 1

        sync_log.notes = f"queued={queued_count} of {len(active_linked)} active linked elections"
        sync_log.status = SyncLog.Status.COMPLETED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["notes", "status", "completed_at"])
        return {"queued": queued_count}

    except Exception as exc:
        logger.exception("sc_enr.sync_results.failed")
        sync_log.error_count = 1
        sync_log.last_error = str(exc)
        sync_log.status = SyncLog.Status.FAILED
        sync_log.completed_at = timezone.now()
        sync_log.save(update_fields=["error_count", "last_error", "status", "completed_at"])
        raise

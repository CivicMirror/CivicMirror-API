from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from results.adapters.registry import list_supported_states

from .models import SyncLog

# Bare 2-letter state/territory codes — used to recognize state-specific
# SyncLog.source values (e.g. "wv_sos", "sc_enr", "tx_goelect" all start
# with their state's code) without a hardcoded source->state mapping table
# that would need manual upkeep every time an integration is added.
_US_STATE_CODES = frozenset([
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "GU", "VI", "AS", "MP",
])

_GLOBAL_SOURCES = frozenset(["civic_api"])

_FULL_CORE_STATES = frozenset([
    "AL", "AZ", "CO", "FL", "GA", "IL", "MA", "MI", "PA", "SC", "TX", "VA", "WA", "WV",
])

_STATE_INTEGRATION_STATES = frozenset(["KY"])


def _source_state_code(source: str) -> str | None:
    """'wv_sos' -> 'WV', 'sc_enr' -> 'SC', 'tx_goelect' -> 'TX'.

    Every current state-specific SyncLog.source value is prefixed with its
    state's 2-letter code followed by an underscore — this derives the
    state from that convention instead of a hand-maintained lookup table.
    Returns None for national/non-state sources (civic_api, openstates,
    fec, congress, census, election_calendar, ...).
    """
    prefix = source.split("_", 1)[0].upper()
    return prefix if prefix in _US_STATE_CODES else None


def _serialize_log(log: SyncLog) -> dict:
    return {
        "last_completed_at": log.completed_at,
        "status": log.status,
        "records_created": log.records_created,
        "records_updated": log.records_updated,
        "records_skipped": log.records_skipped,
    }


def _coverage_tiers(adapter_states: list[str]) -> dict[str, str]:
    tiers = {state: "full" for state in _FULL_CORE_STATES}
    tiers.update({state: "state" for state in _STATE_INTEGRATION_STATES})

    for state in adapter_states:
        tiers.setdefault(state, "results")

    return dict(sorted(tiers.items()))


class CoverageSyncStatusView(APIView):
    """Public, read-only summary of the most recent completed sync per
    source, grouped by state, plus the live set of states with a
    registered results adapter — powers the /coverage page's dynamic
    tier assignment and "last synced" freshness display.
    """
    permission_classes = [AllowAny]

    _COMPLETED_STATUSES = (SyncLog.Status.COMPLETED, SyncLog.Status.COMPLETED_WITH_WARNINGS)

    def get(self, request):
        latest_logs = []
        seen_sources = set()
        completed_logs_by_source_recency = (
            SyncLog.objects
            .filter(status__in=self._COMPLETED_STATUSES)
            .exclude(source="")
            .only(
                "source",
                "completed_at",
                "status",
                "records_created",
                "records_updated",
                "records_skipped",
            )
            .order_by("source", "-completed_at", "-pk")
        )

        for log in completed_logs_by_source_recency:
            if log.source in seen_sources:
                continue
            seen_sources.add(log.source)
            latest_logs.append(log)

        global_sources: dict[str, dict] = {}
        by_state: dict[str, dict[str, dict]] = {}

        for log in latest_logs:
            if log.source in _GLOBAL_SOURCES:
                global_sources[log.source] = _serialize_log(log)
                continue

            state_code = _source_state_code(log.source)
            if state_code is None:
                continue

            by_state.setdefault(state_code, {})[log.source] = _serialize_log(log)

        adapter_states = sorted(list_supported_states())

        return Response({
            "as_of": timezone.now(),
            "global": global_sources,
            "by_state": by_state,
            "adapter_states": adapter_states,
            "coverage_tiers": _coverage_tiers(adapter_states),
        })

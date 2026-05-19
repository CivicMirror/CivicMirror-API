import functools
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils.crypto import constant_time_compare

logger = logging.getLogger(__name__)


def require_internal_task_token(view_func):
    """
    Decorator that validates the Authorization: Bearer <token> header.

    Phase 2: shared-secret validation only (INTERNAL_TASK_TOKEN env var).
    Phase 6: add OIDC verification for Google Cloud Scheduler in production.

    Rules:
    - In production (DEBUG=False) with no INTERNAL_TASK_TOKEN configured, ALL requests are rejected.
    - With INTERNAL_TASK_TOKEN set, only matching tokens are accepted.
    """
    @functools.wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("scheduler.trigger.auth_failed reason=missing_bearer")
            return JsonResponse({"error": "Unauthorized"}, status=401)

        token = auth_header[len("Bearer "):]
        expected = getattr(settings, "INTERNAL_TASK_TOKEN", "")

        if not expected:
            # TODO Phase 6: attempt OIDC verification here before rejecting.
            logger.warning("scheduler.trigger.auth_failed reason=no_token_configured")
            return JsonResponse({"error": "Unauthorized"}, status=401)

        if not constant_time_compare(token, expected):
            logger.warning("scheduler.trigger.auth_failed reason=token_mismatch")
            return JsonResponse({"error": "Unauthorized"}, status=401)

        return view_func(request, *args, **kwargs)

    return _wrapped

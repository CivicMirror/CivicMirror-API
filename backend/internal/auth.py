import functools
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils.crypto import constant_time_compare

logger = logging.getLogger(__name__)


def _verify_oidc_token(token: str) -> bool:
    """Verify a Google OIDC JWT issued by Cloud Scheduler."""
    audience = getattr(settings, "SCHEDULER_OIDC_AUDIENCE", "")
    expected_sa = getattr(settings, "SCHEDULER_SA_EMAIL", "")
    if not audience:
        return False

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        payload = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=audience,
        )
        if expected_sa and payload.get("email") != expected_sa:
            logger.warning(
                "scheduler.trigger.auth_failed reason=unexpected_sa email=%s",
                payload.get("email"),
            )
            return False
        return True
    except Exception as exc:
        logger.warning(
            "scheduler.trigger.auth_failed reason=oidc_verification_failed error=%s",
            exc,
        )
        return False


def require_internal_task_token(view_func):
    """
    Validate the Authorization: Bearer <token> header.

    Accepts either:
    1. Shared-secret (INTERNAL_TASK_TOKEN) — local dev and manual triggers.
    2. Google OIDC JWT (SCHEDULER_OIDC_AUDIENCE) — Cloud Scheduler in production.
    """
    @functools.wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("scheduler.trigger.auth_failed reason=missing_bearer")
            return JsonResponse({"error": "Unauthorized"}, status=401)

        token = auth_header[len("Bearer "):]
        expected = getattr(settings, "INTERNAL_TASK_TOKEN", "")

        if expected and constant_time_compare(token, expected):
            return view_func(request, *args, **kwargs)

        if _verify_oidc_token(token):
            return view_func(request, *args, **kwargs)

        logger.warning("scheduler.trigger.auth_failed reason=token_mismatch")
        return JsonResponse({"error": "Unauthorized"}, status=401)

    return _wrapped

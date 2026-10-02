import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import ApiKey, hash_api_key, prefix_from_raw_key

logger = logging.getLogger('api.access')

LEGACY_KEY_LABEL = 'legacy'
LAST_USED_RESOLUTION = timedelta(minutes=5)

# View attribute values for ``api_key_scope``.
SCOPE_DATA = 'data'      # default: write methods need a read_write key
SCOPE_PUBLIC = 'public'  # public-participation views: any valid key; user auth is enforced by the view


def _touch_last_used(api_key: ApiKey) -> None:
    now = timezone.now()
    if api_key.last_used_at is None or now - api_key.last_used_at >= LAST_USED_RESOLUTION:
        ApiKey.objects.filter(pk=api_key.pk).update(last_used_at=now)
        api_key.last_used_at = now


def _set_on_request(request, api_key, label) -> None:
    # Set on both the DRF Request and the underlying HttpRequest so later code sees it either way.
    for target in (request, getattr(request, '_request', None)):
        if target is not None:
            target.api_key = api_key
            target.api_key_label = label


class HasAPIKey(BasePermission):
    """
    Requires a valid ``X-Api-Key`` header (ADR-010).

    Accepted keys:
      * an active, unexpired ``ApiKey`` (looked up by SHA-256 hash), or
      * the legacy shared ``settings.CIVICMIRROR_API_KEY`` (treated as read_write), if configured.

    Access levels: ``read`` keys may only use SAFE_METHODS on data views. Views that set
    ``api_key_scope = 'public'`` (public mock voting / community) accept any valid key for
    every method, because those views authenticate the end user themselves.

    After this check, ``request.api_key`` is the matched ``ApiKey`` or ``None`` for the legacy key,
    and ``request.api_key_label`` is the key prefix or ``'legacy'``.
    """

    message = 'A valid API key is required.'

    def has_permission(self, request, view):
        presented = request.META.get('HTTP_X_API_KEY', '')
        if not presented:
            return False

        legacy = getattr(settings, 'CIVICMIRROR_API_KEY', '')
        if legacy and constant_time_compare(presented, legacy):
            _set_on_request(request, None, LEGACY_KEY_LABEL)
            can_write = True
        else:
            api_key = ApiKey.objects.usable().filter(hashed_key=hash_api_key(presented)).first()
            if api_key is None:
                prefix = prefix_from_raw_key(presented)
                if prefix:
                    logger.warning('api_key rejected prefix=%s method=%s path=%s', prefix, request.method, request.path)
                return False
            _set_on_request(request, api_key, api_key.prefix)
            _touch_last_used(api_key)
            logger.info('api_key request prefix=%s method=%s path=%s', api_key.prefix, request.method, request.path)
            can_write = api_key.can_write

        if getattr(view, 'api_key_scope', SCOPE_DATA) == SCOPE_PUBLIC:
            return True
        if request.method in SAFE_METHODS or can_write:
            return True
        self.message = 'This API key has read-only access.'
        return False


class IsFirebaseAuthenticated(BasePermission):
    """
    Requires a valid Firebase ID token supplied via FirebaseAuthentication.
    The token must appear as request.auth (a dict with a 'uid' key).
    Use alongside FirebaseAuthentication in authentication_classes.
    """

    message = 'Firebase authentication required.'

    def has_permission(self, request, view):
        return (
            isinstance(request.auth, dict)
            and bool(request.auth.get('uid'))
        )

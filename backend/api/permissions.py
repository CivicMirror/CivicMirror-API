from django.conf import settings
from django.utils.crypto import constant_time_compare
from rest_framework.permissions import BasePermission


class HasAPIKey(BasePermission):
    """
    Requires X-Api-Key header matching settings.CIVICMIRROR_API_KEY.
    If CIVICMIRROR_API_KEY is empty, all requests are rejected.
    """

    def has_permission(self, request, view):
        expected = getattr(settings, 'CIVICMIRROR_API_KEY', '')
        if not expected:
            return False
        api_key = request.META.get('HTTP_X_API_KEY', '')
        return bool(api_key) and constant_time_compare(api_key, expected)

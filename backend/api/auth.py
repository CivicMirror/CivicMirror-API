try:
    import firebase_admin
    import firebase_admin.auth as fb_auth
    _FIREBASE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _FIREBASE_AVAILABLE = False

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class FirebaseAuthentication(BaseAuthentication):
    """
    DRF authentication backend for Firebase ID tokens.

    On success, sets request.auth = decoded Firebase token dict (contains 'uid' key).
    Returns None (pass-through) if no Authorization: Bearer header is present,
    or if Firebase is not initialized/enabled.
    Raises AuthenticationFailed (401) if a Bearer token is present but invalid.
    """

    def authenticate(self, request):
        from django.conf import settings

        if not getattr(settings, 'FIREBASE_AUTH_ENABLED', True):
            return None

        if not _FIREBASE_AVAILABLE:
            return None  # pragma: no cover

        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return None

        token = auth_header.split(' ', 1)[1]

        try:
            firebase_admin.get_app()
        except ValueError:
            # Firebase not initialized — treat as unauthenticated, not an error
            return None

        try:
            decoded = fb_auth.verify_id_token(token)
            return (None, decoded)
        except AuthenticationFailed:
            raise
        except Exception:
            raise AuthenticationFailed('Invalid or expired Firebase token')

    def authenticate_header(self, request):
        return 'Bearer realm="CivicMirror"'

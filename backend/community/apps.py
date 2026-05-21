import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class CommunityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'community'
    verbose_name = 'Community'

    def ready(self):
        _init_firebase()


def _init_firebase():
    from django.conf import settings

    if not getattr(settings, 'FIREBASE_AUTH_ENABLED', True):
        return

    try:
        import firebase_admin

        try:
            firebase_admin.get_app()
            return  # already initialized
        except ValueError:
            pass

        cred_file = getattr(settings, 'FIREBASE_CREDENTIALS_FILE', None)
        if cred_file:
            cred = firebase_admin.credentials.Certificate(cred_file)
        else:
            cred = firebase_admin.credentials.ApplicationDefault()

        firebase_admin.initialize_app(cred)
        logger.info('Firebase Admin initialized')
    except ImportError:
        logger.warning('firebase-admin not installed; Firebase auth disabled')
    except Exception as exc:
        logger.warning('Firebase Admin initialization failed: %s', exc)

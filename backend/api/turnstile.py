"""
Cloudflare Turnstile verification for public account registration (#202).

Enabled only when ``TURNSTILE_SECRET_KEY`` is set, so the API can be deployed before the FrontEnd
sends tokens. Verification fails closed: if Cloudflare can't be reached, registration is refused.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger('api.access')

SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'
TIMEOUT_SECONDS = 5


def turnstile_enabled() -> bool:
    return bool(getattr(settings, 'TURNSTILE_SECRET_KEY', ''))


def verify_turnstile(token, remote_ip: str | None = None) -> bool:
    """Return True if Cloudflare confirms ``token`` (and its action, when one is configured)."""
    if not isinstance(token, str) or not token or len(token) > 2048:
        return False
    payload = {'secret': settings.TURNSTILE_SECRET_KEY, 'response': token}
    if remote_ip:
        payload['remoteip'] = remote_ip
    try:
        response = requests.post(SITEVERIFY_URL, data=payload, timeout=TIMEOUT_SECONDS)
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning('turnstile siteverify unavailable: %s', exc.__class__.__name__)
        return False

    if not result.get('success'):
        logger.info('turnstile rejected error_codes=%s', ','.join(result.get('error-codes', [])) or '-')
        return False
    expected_action = getattr(settings, 'TURNSTILE_EXPECTED_ACTION', '')
    if expected_action and result.get('action') != expected_action:
        logger.info('turnstile rejected action=%s expected=%s', result.get('action'), expected_action)
        return False
    return True

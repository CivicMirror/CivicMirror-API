"""
Rate limits.

* ``ApiKeyRateThrottle``: per service API key (ADR-010).
* Public-participation throttles (#202): registration, login, mock voting, and community race
  submission, keyed on the end user and/or the client IP.

All counters live in ``caches['throttle']`` (Redis in production, LocMem in dev/test).
"""
import hashlib
import ipaddress
import logging

from django.conf import settings
from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger('api.access')

_warned_unresolved_ip: set[str] = set()


def get_request_uid(request) -> str | None:
    """Return a stable uid string for either Firebase or Django Token auth."""
    if isinstance(request.auth, dict):
        return request.auth.get('uid')
    if request.user and request.user.is_authenticated:
        return f'user:{request.user.pk}'
    return None


def get_client_ip(request) -> str | None:
    """
    Resolve the end client's IP from trusted proxy headers, or return None.

    Production traffic arrives Cloudflare -> tunnel -> FrontEnd nginx -> API, so ``REMOTE_ADDR``
    is always the nginx container and is never used. In order:

    1. ``CIVICMIRROR_CLIENT_IP_HEADER`` (default ``HTTP_CF_CONNECTING_IP``). Cloudflare overwrites
       this header, so clients can't prefix-spoof it the way they can ``X-Forwarded-For``.
    2. ``X-Forwarded-For``, taking the entry ``CIVICMIRROR_CLIENT_IP_XFF_PROXIES`` from the right,
       only when that setting is > 0.

    Returning None (instead of falling back to ``REMOTE_ADDR``) means a misconfigured proxy chain
    disables IP limits rather than putting every user in one shared bucket.
    """
    header = getattr(settings, 'CIVICMIRROR_CLIENT_IP_HEADER', 'HTTP_CF_CONNECTING_IP')
    if header:
        ip = _valid_ip(request.META.get(header, ''))
        if ip:
            return ip
    num_proxies = getattr(settings, 'CIVICMIRROR_CLIENT_IP_XFF_PROXIES', 0)
    if num_proxies > 0:
        addrs = [a.strip() for a in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if a.strip()]
        if len(addrs) >= num_proxies:
            return _valid_ip(addrs[-num_proxies])
    return None


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


class _ThrottleCacheMixin:
    @property
    def cache(self):
        return caches['throttle']


class ApiKeyRateThrottle(_ThrottleCacheMixin, SimpleRateThrottle):
    """
    Per-service-key rate limit (ADR-010).

    Runs after ``HasAPIKey`` (DRF checks permissions before throttles), so ``request.api_key``
    is already set. Requests without a DB-backed key are not throttled here: keyless AllowAny
    views, and the legacy shared key, which fronts all public FrontEnd traffic.

    The rate is the key's ``throttle_rate``, falling back to ``CIVICMIRROR_API_KEY_DEFAULT_RATE``;
    ``'none'`` disables throttling for that key.
    """

    scope = 'api_key'

    def get_rate(self):
        # The rate is per key, so it is resolved in allow_request() instead.
        return None

    def allow_request(self, request, view):
        api_key = getattr(request, 'api_key', None)
        if api_key is None:
            return True
        rate = api_key.throttle_rate or getattr(settings, 'CIVICMIRROR_API_KEY_DEFAULT_RATE', '')
        if not rate or rate == 'none':
            return True
        self.rate = rate
        self.num_requests, self.duration = self.parse_rate(rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        # Keyed on the random prefix, not the pk, so counters never carry over to a reused id.
        return self.cache_format % {'scope': self.scope, 'ident': request.api_key.prefix}


class PublicRateThrottle(_ThrottleCacheMixin, SimpleRateThrottle):
    """
    Base for public-participation throttles (#202).

    Rates come from ``settings.CIVICMIRROR_THROTTLE_RATES[scope]`` and are read on every request
    (DRF's own ``THROTTLE_RATES`` is captured at import). An empty rate or ``'none'`` disables the scope.
    ``methods`` limits which HTTP methods count; other methods pass untouched.
    """

    methods: tuple[str, ...] = ('POST',)

    def get_rate(self):
        rate = getattr(settings, 'CIVICMIRROR_THROTTLE_RATES', {}).get(self.scope, '')
        return None if rate in ('', 'none') else rate

    def allow_request(self, request, view):
        if request.method not in self.methods:
            return True
        # Re-read the rate per request so settings changes apply without a restart in tests.
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        allowed = super().allow_request(request, view)
        if not allowed:
            logger.warning('throttled scope=%s path=%s', self.scope, request.path)
        return allowed

    def get_ident_value(self, request) -> str | None:
        raise NotImplementedError

    def get_cache_key(self, request, view):
        ident = self.get_ident_value(request)
        if ident is None:
            return None  # can't identify the caller; skip rather than share one bucket
        return self.cache_format % {'scope': self.scope, 'ident': ident}


class _ClientIPThrottle(PublicRateThrottle):
    def get_ident_value(self, request):
        ip = get_client_ip(request)
        if ip is None and self.scope not in _warned_unresolved_ip:
            _warned_unresolved_ip.add(self.scope)
            logger.warning(
                'client IP unresolved for scope=%s; IP rate limit skipped. Check CIVICMIRROR_CLIENT_IP_HEADER '
                'and the proxy chain.', self.scope,
            )
        return ip


class _UserThrottle(PublicRateThrottle):
    def get_ident_value(self, request):
        return get_request_uid(request)  # unauthenticated requests are rejected by the view itself


class RegisterIPThrottle(_ClientIPThrottle):
    scope = 'register_ip'

    def get_ident_value(self, request):
        ip = super().get_ident_value(request)
        logger.info('public auth attempt scope=%s client_ip=%s', self.scope, ip or 'unresolved')
        return ip


class LoginIPThrottle(_ClientIPThrottle):
    scope = 'login_ip'

    def get_ident_value(self, request):
        ip = super().get_ident_value(request)
        logger.info('public auth attempt scope=%s client_ip=%s', self.scope, ip or 'unresolved')
        return ip


class LoginUsernameThrottle(PublicRateThrottle):
    """
    Per-username login limit, against credential stuffing on one account. Counts all attempts, so
    an attacker could temporarily lock out a known username; keep this rate generous and rely on
    the per-IP limit first.
    """

    scope = 'login_username'

    def get_ident_value(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        username = data.get('username')
        if not isinstance(username, str) or not username.strip():
            return None
        return hashlib.sha256(username.strip().lower().encode('utf-8')).hexdigest()[:32]


class VoteUserThrottle(_UserThrottle):
    scope = 'vote_user'


class VoteIPThrottle(_ClientIPThrottle):
    scope = 'vote_ip'


class CommunityCreateUserThrottle(_UserThrottle):
    scope = 'community_create_user'


class CommunityCreateIPThrottle(_ClientIPThrottle):
    scope = 'community_create_ip'

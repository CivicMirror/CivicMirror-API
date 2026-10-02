from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class ApiKeyRateThrottle(SimpleRateThrottle):
    """
    Per-service-key rate limit (ADR-010).

    Runs after ``HasAPIKey`` (DRF checks permissions before throttles), so ``request.api_key``
    is already set. Requests without a DB-backed key are not throttled here: keyless AllowAny
    views, and the legacy shared key, which fronts all public FrontEnd traffic.

    The rate is the key's ``throttle_rate``, falling back to ``CIVICMIRROR_API_KEY_DEFAULT_RATE``;
    ``'none'`` disables throttling for that key. Counters live in the default cache, so limits are
    only shared across processes when ``REDIS_URL`` is configured.
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

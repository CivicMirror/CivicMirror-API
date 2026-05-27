class CaSosError(Exception):
    """Non-retryable CA SOS error (bad config, unexpected response shape)."""


class CaSosRetryableError(CaSosError):
    """Retryable CA SOS error (network failure, rate limit, 5xx)."""

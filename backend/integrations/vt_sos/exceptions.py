class VtSosError(Exception):
    """Non-retryable Vermont SOS error (bad config, unexpected response shape)."""


class VtSosRetryableError(VtSosError):
    """Retryable Vermont SOS error (network failure, rate limit, 5xx)."""

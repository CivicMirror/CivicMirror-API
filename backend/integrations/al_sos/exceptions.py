class AlSosError(Exception):
    """Non-retryable Alabama SOS integration error."""


class AlSosRetryableError(AlSosError):
    """Transient Alabama SOS integration error that should be retried."""

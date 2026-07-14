class GaSosError(Exception):
    """Non-retryable Georgia SOS integration error."""


class GaSosRetryableError(GaSosError):
    """Transient Georgia SOS integration error that warrants a Celery retry."""

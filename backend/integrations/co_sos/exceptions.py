class CoSosError(Exception):
    """Non-retryable Colorado SOS integration error."""


class CoSosRetryableError(CoSosError):
    """Transient error that warrants a Celery retry."""

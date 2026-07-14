class KySosError(Exception):
    """Non-retryable Kentucky SOS integration error."""


class KySosRetryableError(KySosError):
    """Transient error that warrants a Celery retry."""

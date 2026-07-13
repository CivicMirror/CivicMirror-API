class MnSosError(Exception):
    """Non-retryable Minnesota SOS integration error."""


class MnSosRetryableError(MnSosError):
    """Transient error that warrants a Celery retry."""

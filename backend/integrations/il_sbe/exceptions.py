class IlSbeError(Exception):
    """Non-retryable Illinois SBE integration error."""


class IlSbeRetryableError(IlSbeError):
    """Transient error that warrants a Celery retry."""

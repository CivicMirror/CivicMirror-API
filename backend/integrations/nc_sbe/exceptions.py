class NcSbeError(Exception):
    """Non-retryable NC State Board of Elections error."""


class NcSbeRetryableError(NcSbeError):
    """Transient error — Celery should retry."""

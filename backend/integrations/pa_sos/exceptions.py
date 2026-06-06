class PaSosError(Exception):
    """Non-retryable PA SOS integration error."""

class PaSosRetryableError(PaSosError):
    """Transient error — Celery should retry."""

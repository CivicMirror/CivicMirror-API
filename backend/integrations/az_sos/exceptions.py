class AzSosError(Exception):
    """Non-retryable AZ SOS integration error."""

class AzSosRetryableError(AzSosError):
    """Transient error — Celery should retry."""

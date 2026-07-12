class NjElectionsError(Exception):
    """Non-retryable New Jersey elections integration error."""


class NjElectionsRetryableError(NjElectionsError):
    """Transient error that warrants a Celery retry."""

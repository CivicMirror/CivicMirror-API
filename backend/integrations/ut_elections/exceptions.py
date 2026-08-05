class UtElectionsError(Exception):
    """Non-retryable Utah elections integration error."""


class UtElectionsRetryableError(UtElectionsError):
    """Transient error that warrants a retry (network/5xx/soft-404)."""

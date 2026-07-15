class TnSosError(Exception):
    """Non-retryable Tennessee SOS integration error."""


class TnSosRetryableError(TnSosError):
    """Transient Tennessee SOS integration error that warrants retry."""

class MiSosError(Exception):
    """Non-retryable Michigan SOS integration error."""


class MiSosRetryableError(MiSosError):
    """Transient Michigan SOS integration error that should retry."""

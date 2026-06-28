class OhSosError(Exception):
    """Non-retryable Ohio SOS error."""


class OhSosRetryableError(OhSosError):
    """Transient Ohio SOS error — safe to retry."""

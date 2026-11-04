class AkSosError(Exception):
    """Non-retryable Alaska Division of Elections integration error."""


class AkSosRetryableError(AkSosError):
    """Transient error (navigation/AJAX timeout) that warrants a retry."""

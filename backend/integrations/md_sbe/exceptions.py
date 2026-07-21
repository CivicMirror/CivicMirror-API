class MdSbeError(Exception):
    """Non-retryable Maryland SBE integration error."""


class MdSbeRetryableError(MdSbeError):
    """Transient error that warrants a retry (network/5xx)."""

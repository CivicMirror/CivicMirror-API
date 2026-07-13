class OrSosError(Exception):
    """Base exception for Oregon SOS integration failures."""


class OrSosUnsupportedDocumentError(OrSosError):
    """Raised when a discovered Oregon result document cannot be parsed yet."""

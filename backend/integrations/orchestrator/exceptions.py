class MatchConflictError(Exception):
    """Raised when a match is found but has irreconcilable conflicts."""


class AmbiguousMatchError(Exception):
    """Raised when multiple candidates or races could match."""


class NoRaceFoundError(Exception):
    """Raised when an enrichment-only source cannot resolve a race."""

class HawaiiOlvrError(Exception):
    """Base error for Hawaii OLVR candidate-report ingestion."""


class HawaiiOlvrRetryableError(HawaiiOlvrError):
    """Temporary failure fetching the landing page or export."""

from django.core.exceptions import ImproperlyConfigured


def _require_exact_name(kind: str, configured: str, expected: str) -> None:
    if not configured or configured != expected:
        raise ImproperlyConfigured(
            f"CivicMirror 2.0 {kind} isolation check failed: "
            f"configured {configured!r}; expected {expected!r}."
        )


def require_database_name(configured: str, expected: str) -> None:
    _require_exact_name("database", configured, expected)


def require_task_queue(configured: str, expected: str = "civicmirror_2_0") -> None:
    _require_exact_name("task queue", configured, expected)

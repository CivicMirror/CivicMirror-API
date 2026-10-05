from __future__ import annotations

import sys
from collections.abc import Sequence


class UnsupportedPythonError(RuntimeError):
    """Raised when CivicMirror starts under an unsupported interpreter."""


def require_supported_python(version_info: Sequence[int] = sys.version_info) -> None:
    """Require the repository's single supported Python minor version."""
    major_minor = tuple(version_info[:2])
    if major_minor != (3, 13):
        actual = ".".join(str(part) for part in version_info[:3])
        raise UnsupportedPythonError(
            f"CivicMirror requires Python >=3.13,<3.14; detected {actual}. "
            "Use the repository Python 3.13 environment or the 2.0 development container."
        )

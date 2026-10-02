"""
OpenAPI schema scope for the public API docs (/api/docs/ and /api/schema/).

Only the documented, versioned API (/api/v1/) is published. Excluded:
  * internal task triggers (/internal/)
  * account/auth endpoints (/api/auth/*, /api/users/me/profile/)
  * the unversioned /api/ alias, which duplicates every /api/v1/ route
  * the schema endpoint itself
"""

PUBLIC_PREFIX = "/api/v1/"
EXCLUDED_PREFIXES = (
    "/internal/",
    "/api/auth/",
    "/api/users/me/profile/",
    "/api/schema/",
    "/api/docs/",
)


def is_public_path(path: str) -> bool:
    return path.startswith(PUBLIC_PREFIX) and not path.startswith(EXCLUDED_PREFIXES)


def preprocess_public_endpoints(endpoints):
    """drf-spectacular PREPROCESSING_HOOK: keep only public API endpoints."""
    return [endpoint for endpoint in endpoints if is_public_path(endpoint[0])]

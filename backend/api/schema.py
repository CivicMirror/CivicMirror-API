"""
OpenAPI schema scope for the public API docs (/api/docs/ and /api/schema/).

Only the documented, versioned API (/api/v1/) is published. Excluded:
  * internal task triggers (/internal/)
  * account/auth endpoints (/api/auth/*, /api/users/me/profile/)
  * public-participation endpoints (mock voting, tallies, community races, /users/*): any view
    with api_key_scope = 'public'. They serve the FrontEnd's logged-in users, not API developers.
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


def is_participation_view(callback) -> bool:
    from .permissions import SCOPE_PUBLIC

    view_class = getattr(callback, "cls", None)
    return getattr(view_class, "api_key_scope", None) == SCOPE_PUBLIC


def preprocess_public_endpoints(endpoints):
    """drf-spectacular PREPROCESSING_HOOK: keep only the developer-facing data API."""
    return [
        (path, path_regex, method, callback)
        for path, path_regex, method, callback in endpoints
        if is_public_path(path) and not is_participation_view(callback)
    ]

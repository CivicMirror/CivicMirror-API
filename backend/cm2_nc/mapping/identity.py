import hashlib
import re
import unicodedata


def normalize_identity_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.casefold().split())


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")
    return slug[:48] or "record"


def stable_public_id(kind: str, *parts: str) -> str:
    normalized_kind = _slug(normalize_identity_part(kind))
    normalized_parts = tuple(normalize_identity_part(part) for part in parts)
    digest_input = "\x1f".join((normalized_kind, *normalized_parts))
    digest = hashlib.sha256(digest_input.encode()).hexdigest()[:16]
    readable = "/".join(_slug(part) for part in normalized_parts[:4])
    return f"nc/{normalized_kind}/{readable}/{digest}"

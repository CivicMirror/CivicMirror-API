import hashlib
import re
import secrets

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

KEY_PREFIX_LABEL = 'cm'
_RATE_RE = re.compile(r'^\d+/(s|sec|second|m|min|minute|h|hour|d|day)$')


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode('utf-8')).hexdigest()


def prefix_from_raw_key(raw_key: str) -> str:
    """Return the public prefix (``cm_xxxxxxxx``) embedded in a raw key, or '' if malformed."""
    parts = raw_key.split('_', 2)
    if len(parts) == 3 and parts[0] == KEY_PREFIX_LABEL and parts[1]:
        return f'{parts[0]}_{parts[1]}'
    return ''


def validate_throttle_rate(value: str) -> None:
    if value and value != 'none' and not _RATE_RE.match(value):
        raise ValidationError("Use '<count>/<second|minute|hour|day>', 'none', or leave blank for the default.")


class ApiKeyQuerySet(models.QuerySet):
    def usable(self):
        now = timezone.now()
        return self.filter(is_active=True).filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now))


class ApiKey(models.Model):
    """
    A service API key issued to an individually approved client (see ADR-010).

    Only the SHA-256 hash of the key is stored. The plaintext is returned once,
    by ``ApiKey.issue()``, and cannot be recovered afterwards.
    """

    class AccessLevel(models.TextChoices):
        READ = 'read', 'Read'
        READ_WRITE = 'read_write', 'Read / write'

    name = models.CharField(max_length=120, help_text='Client this key belongs to, e.g. "CivicData".')
    owner = models.CharField(max_length=200, blank=True, help_text='Contact person or organization.')
    prefix = models.CharField(max_length=32, unique=True, editable=False)
    hashed_key = models.CharField(max_length=64, unique=True, editable=False)
    access_level = models.CharField(max_length=16, choices=AccessLevel.choices, default=AccessLevel.READ)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    throttle_rate = models.CharField(
        max_length=32,
        blank=True,
        validators=[validate_throttle_rate],
        help_text="e.g. '1000/hour'. Blank uses CIVICMIRROR_API_KEY_DEFAULT_RATE; 'none' disables throttling.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = ApiKeyQuerySet.as_manager()

    class Meta:
        ordering = ['name', 'created_at']
        verbose_name = 'API key'
        verbose_name_plural = 'API keys'

    def __str__(self):
        return f'{self.name} ({self.prefix}, {self.access_level})'

    @property
    def can_write(self) -> bool:
        return self.access_level == self.AccessLevel.READ_WRITE

    def assign_new_secret(self) -> str:
        """Generate a fresh prefix and secret on this instance; return the plaintext key. Caller saves."""
        while True:
            prefix = f'{KEY_PREFIX_LABEL}_{secrets.token_hex(4)}'
            if not ApiKey.objects.filter(prefix=prefix).exists():
                break
        raw_key = f'{prefix}_{secrets.token_urlsafe(32)}'
        self.prefix = prefix
        self.hashed_key = hash_api_key(raw_key)
        return raw_key

    @classmethod
    def issue(cls, **fields) -> tuple['ApiKey', str]:
        """Create and save a new key. Returns ``(api_key, plaintext)``; the plaintext is not stored."""
        api_key = cls(**fields)
        raw_key = api_key.assign_new_secret()
        api_key.full_clean()
        api_key.save()
        return api_key, raw_key

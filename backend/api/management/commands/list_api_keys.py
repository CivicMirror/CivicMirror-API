"""
List service API keys (ADR-010). Never prints secrets.

Usage:
    python manage.py list_api_keys          # active keys
    python manage.py list_api_keys --all    # include revoked and expired keys
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import ApiKey


class Command(BaseCommand):
    help = "List service API keys"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Include inactive and expired keys.")

    def handle(self, *args, **options):
        keys = ApiKey.objects.all() if options["all"] else ApiKey.objects.usable()
        now = timezone.now()
        rows = [("PREFIX", "NAME", "ACCESS", "STATUS", "EXPIRES", "LAST USED")]
        for key in keys:
            if not key.is_active:
                status = "revoked"
            elif key.expires_at and key.expires_at <= now:
                status = "expired"
            else:
                status = "active"
            rows.append((
                key.prefix,
                key.name,
                key.access_level,
                status,
                key.expires_at.date().isoformat() if key.expires_at else "-",
                key.last_used_at.isoformat(timespec="minutes") if key.last_used_at else "never",
            ))
        if len(rows) == 1:
            self.stdout.write("No API keys.")
            return
        widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
        for row in rows:
            self.stdout.write("  ".join(str(value).ljust(width) for value, width in zip(row, widths)).rstrip())

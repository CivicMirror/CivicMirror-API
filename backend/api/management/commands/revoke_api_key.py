"""
Deactivate a service API key by its public prefix (ADR-010).

Usage:
    python manage.py revoke_api_key cm_1a2b3c4d

Revocation takes effect on the next request. The record is kept for attribution.
"""

from django.core.management.base import BaseCommand, CommandError

from api.models import ApiKey


class Command(BaseCommand):
    help = "Deactivate a service API key by prefix"

    def add_arguments(self, parser):
        parser.add_argument("prefix", help="Key prefix, e.g. cm_1a2b3c4d (see list_api_keys).")

    def handle(self, *args, **options):
        try:
            api_key = ApiKey.objects.get(prefix=options["prefix"])
        except ApiKey.DoesNotExist as exc:
            raise CommandError(f"No API key with prefix {options['prefix']!r}") from exc
        if not api_key.is_active:
            self.stdout.write(f"{api_key} is already inactive.")
            return
        api_key.is_active = False
        api_key.save(update_fields=["is_active"])
        self.stdout.write(self.style.SUCCESS(f"Revoked {api_key}"))

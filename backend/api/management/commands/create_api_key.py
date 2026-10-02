"""
Issue a service API key to an individually approved client (ADR-010).

Usage:
    python manage.py create_api_key --name "CivicData" --access read
    python manage.py create_api_key --name "Jane Tester" --owner "jane@example.org" \
        --access read_write --expires 2027-01-01 --rate 500/hour

The plaintext key is printed once and is not stored; only its SHA-256 hash is saved.
"""

from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from api.models import ApiKey


class Command(BaseCommand):
    help = "Create a service API key and print it once"

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Client name, e.g. CivicData.")
        parser.add_argument("--owner", default="", help="Contact person or organization.")
        parser.add_argument(
            "--access",
            choices=[c.value for c in ApiKey.AccessLevel],
            default=ApiKey.AccessLevel.READ,
            help="Access level (default: read).",
        )
        parser.add_argument("--expires", default=None, help="Expiry date (YYYY-MM-DD), end of day server time.")
        parser.add_argument("--rate", default="", help="Throttle rate, e.g. 500/hour, or 'none'. Blank = default.")
        parser.add_argument("--notes", default="", help="Free-text notes, e.g. approval reference.")

    def handle(self, *args, **options):
        expires_at = None
        if options["expires"]:
            try:
                day = datetime.strptime(options["expires"], "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError("--expires must be YYYY-MM-DD") from exc
            expires_at = timezone.make_aware(datetime.combine(day, time.max))
            if expires_at <= timezone.now():
                raise CommandError("--expires must be in the future")

        try:
            api_key, raw_key = ApiKey.issue(
                name=options["name"],
                owner=options["owner"],
                access_level=options["access"],
                expires_at=expires_at,
                throttle_rate=options["rate"],
                notes=options["notes"],
            )
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc

        self.stdout.write(self.style.SUCCESS(f"Created {api_key}"))
        self.stdout.write("API key (shown once, store it securely):")
        self.stdout.write(raw_key)

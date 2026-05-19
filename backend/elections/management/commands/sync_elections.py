from django.core.management.base import BaseCommand

from integrations.civic.tasks import sync_elections


class Command(BaseCommand):
    help = "Sync elections from Google Civic API (runs synchronously)."

    def handle(self, *args, **options):
        self.stdout.write("Starting sync_elections...")
        result = sync_elections()
        self.stdout.write(self.style.SUCCESS(f"Done: {result}"))

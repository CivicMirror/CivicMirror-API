from django.core.management.base import BaseCommand

from results.tasks import poll_pending_results


class Command(BaseCommand):
    help = "Poll pending elections for official results synchronously."

    def handle(self, *args, **options):
        result = poll_pending_results()
        queued = result.get("queued", 0) if isinstance(result, dict) else 0
        self.stdout.write(
            self.style.SUCCESS(f"Queued {queued} elections for results polling.")
        )

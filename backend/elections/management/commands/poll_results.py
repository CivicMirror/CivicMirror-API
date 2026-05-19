from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Poll pending elections for official results (implemented in Phase 4)."

    def handle(self, *args, **options):
        raise CommandError(
            "poll_results is not yet implemented. This command will be available in Phase 4."
        )

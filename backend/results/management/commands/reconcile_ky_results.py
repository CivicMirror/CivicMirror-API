"""Preview Kentucky reconciliation without database or cache writes by default."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from results.ky_reconciliation import run_ky_ingestion


class Command(BaseCommand):
    help = 'Reconcile KY XML; default is read-only. --apply persists verified contests atomically.'

    def add_arguments(self, parser):
        parser.add_argument('--election-id', type=int, required=True)
        parser.add_argument('--snapshot-dir', help='Directory containing captured dataset XML files')
        parser.add_argument('--report', help='Write complete JSON report to this path (otherwise stdout)')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--contest-id', action='append', help='Pilot only these source contests with --apply')
        parser.add_argument('--expect-rows', type=int)
        parser.add_argument('--expect-reported-contests', type=int)
        parser.add_argument('--expect-no-results', type=int)

    def handle(self, *args, **options):
        # Snapshot assertions must be checked BEFORE persistence.
        if options['apply'] and any(options[k] is not None for k in (
            'expect_rows', 'expect_reported_contests', 'expect_no_results',
        )):
            raise CommandError('Use snapshot assertions with the read-only dry run before --apply')
        report = run_ky_ingestion(options['election_id'], snapshot_dir=options['snapshot_dir'],
                                  contest_ids=set(options['contest_id'] or []), apply=options['apply'])
        for option, key in (('expect_rows', 'source_rows'), ('expect_reported_contests', 'reported_contests'),
                            ('expect_no_results', 'no_result_contests')):
            expected = options[option]
            if expected is not None and report.get(key) != expected:
                raise CommandError(f'Snapshot assertion failed: {key}={report.get(key)} expected={expected}')
        payload = json.dumps(report, indent=2, sort_keys=True)
        if options['report']:
            Path(options['report']).write_text(payload + '\n')
            self.stdout.write(json.dumps({k: v for k, v in report.items() if k != 'contests'}, sort_keys=True))
        else:
            self.stdout.write(payload)
        if report.get('status') == 'unavailable':
            raise CommandError(report['reason'] or 'Kentucky feed unavailable')

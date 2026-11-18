"""Archive visits that were checked out more than N days ago.

Schedule this on cron / a systemd timer (e.g. nightly) to keep the visit
feed focused on active and recent history. Only visits already CHECKED_OUT
and older than ``--days`` (default 30) are moved to ARCHIVED; in-progress and
pending visits are never touched.

Every archived visit gets a ``Visit archived`` audit row, written in the same
transaction as the status change, so the console audit log explains the
transition even though the job has no operator.
"""

from django.core.management.base import BaseCommand

from visits.services import archive_old_visits


class Command(BaseCommand):
    help = "Archive visits checked out more than N days ago (default 30)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Archive visits checked out more than this many days ago.",
        )
        parser.add_argument(
            "--organization",
            type=int,
            default=None,
            help="Restrict archival to one organization id (default: all).",
        )

    def handle(self, *args, **options):
        count = archive_old_visits(
            days=options["days"], organization=options["organization"]
        )
        self.stdout.write(
            self.style.SUCCESS(f"Archived {count} visit(s).")
        )
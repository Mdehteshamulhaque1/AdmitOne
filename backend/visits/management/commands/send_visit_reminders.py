"""Sweep command for automatic visit reminders (Feature #5).

Schedule this on cron / a systemd timer more often than
``REMINDER_SWEEP_WINDOW_HOURS`` (default 2 hours), e.g. every 15-30 minutes.
"""

from django.core.management.base import BaseCommand

from visits.reminders import send_due_visit_reminders


class Command(BaseCommand):
    help = "Send due visit reminders (Feature #5)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending anything.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        summary = send_due_visit_reminders(dry_run=dry_run)
        if dry_run:
            verb = "Would send"
        else:
            verb = "Sent"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {summary['sent']} reminder(s) "
                f"({summary['attempted']} attempted, {summary['skipped']} skipped, "
                f"{summary['failed']} failed, {summary['ineligible']} ineligible)."
            )
        )
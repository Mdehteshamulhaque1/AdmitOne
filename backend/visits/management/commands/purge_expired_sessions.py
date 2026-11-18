"""Delete expired visitor-account sessions.

Sessions are short-lived rows whose only use is to authenticate a bearer
token; once ``expires_at`` has passed they are dead weight. Schedule this
alongside ``archive_old_visits`` (cron / Render cron job), e.g. daily.
"""

from django.core.management.base import BaseCommand

from visits.visitor_accounts import purge_expired_sessions


class Command(BaseCommand):
    help = "Remove expired visitor account sessions."

    def handle(self, *args, **options):
        self.stdout.write(f"Purged {purge_expired_sessions()} expired visitor account session(s).")

"""Production email configuration and delivery observability.

The bug this file exists for: ``EMAIL_BACKEND`` defaulted to the console
backend unconditionally, and ``EMAIL_USE_TLS`` was parsed with ``== "True"``.
Together those meant a production deployment could be configured with
``EMAIL_USE_TLS=true`` (the natural spelling) and get *no TLS*, and could be
running a backend that accepts every message and delivers none of them --
with no error anywhere.

Two things are asserted here:

* configuration is rejected at startup, before the server takes a request, and
* a send that does not reach a human is reported as a failure rather than a
  success.
"""

import logging
import os
import subprocess
import sys
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from config import env as envmod
from config import settings as settings_mod
from visits import notifications
from visits.emails import DeliveryResult, EmailDeliveryError, deliver

# A complete, valid production mail configuration. Tests start from this and
# remove exactly the one thing they are testing, so a failure names the
# missing variable rather than an unrelated one.
VALID_PROD_EMAIL = {
    "ENVIRONMENT": "production",
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_HOST": "smtp.sendgrid.net",
    "EMAIL_PORT": 587,
    "EMAIL_USE_TLS": True,
    "EMAIL_USE_SSL": False,
    "EMAIL_HOST_USER": "apikey",
    "EMAIL_HOST_PASSWORD": "SG.super-secret-value",
    "DEFAULT_FROM_EMAIL": "no-reply@securegate.test",
    "EMAIL_TIMEOUT": 30,
}


def _settings_with(**overrides):
    """Run the real validator with the given settings, and clean up after.

    Calls ``config.settings._validate_production_email`` with its module globals
    patched, so the real logic runs. Reloading ``config.settings`` instead would
    re-run ``django.setup()`` state and leak into unrelated tests.

    The environment is patched as well as the globals: the validator checks
    ``os.environ`` for ``EMAIL_HOST`` to reject the guessed
    ``smtp.gmail.com`` default, so a global-only patch would not be enough.
    A value of ``None`` unsets the environment variable.
    """
    values = dict(VALID_PROD_EMAIL)
    values.update(overrides)
    patches = []
    for key, value in values.items():
        if key == "ENVIRONMENT":
            continue
        patches.append(mock.patch.object(settings_mod, key, value))
        if value is None:
            patches.append(mock.patch.dict(os.environ, {key: ""}, clear=False))
            os.environ.pop(key, None)
        else:
            patches.append(mock.patch.dict(os.environ, {key: str(value)}, clear=False))
    for patch in patches:
        patch.start()
    try:
        settings_mod._validate_production_email()
    finally:
        for patch in reversed(patches):
            patch.stop()


class EnvBoolTests(SimpleTestCase):
    """``EMAIL_USE_TLS=true`` must not silently mean False."""

    def test_accepts_every_truthy_spelling(self):
        for raw in ("true", "True", "TRUE", "tRuE", "1", "yes", "YES", "on", "y", "t"):
            with self.subTest(value=raw):
                with mock.patch.dict(os.environ, {"FLAG": raw}, clear=False):
                    self.assertTrue(envmod.env_bool("FLAG"))

    def test_accepts_every_falsy_spelling(self):
        for raw in ("false", "False", "FALSE", "0", "no", "NO", "off", "n", "f", ""):
            with self.subTest(value=raw):
                with mock.patch.dict(os.environ, {"FLAG": raw}, clear=False):
                    self.assertFalse(envmod.env_bool("FLAG"))

    def test_tolerates_surrounding_whitespace(self):
        # A trailing space is what a .env heredoc or a Render dashboard paste
        # produces, and it used to turn `true` into False.
        for raw in (" true ", "TRUE\n", " 1 "):
            with self.subTest(value=raw):
                with mock.patch.dict(os.environ, {"FLAG": raw}, clear=False):
                    self.assertTrue(envmod.env_bool("FLAG"))

    def test_unset_uses_the_default(self):
        environ = {k: v for k, v in os.environ.items() if k != "FLAG"}
        with mock.patch.dict(os.environ, environ, clear=True):
            self.assertTrue(envmod.env_bool("FLAG", default=True))
            self.assertFalse(envmod.env_bool("FLAG", default=False))

    def test_garbage_raises_instead_of_guessing(self):
        # The whole point: guessing False for a typo is how TLS gets disabled.
        for raw in ("flase", "maybe", "tru", "2", "yess"):
            with self.subTest(value=raw):
                with mock.patch.dict(os.environ, {"FLAG": raw}, clear=False):
                    with self.assertRaises(ValueError):
                        envmod.env_bool("FLAG")

    def test_required_and_missing_raises(self):
        environ = {k: v for k, v in os.environ.items() if k != "FLAG"}
        with mock.patch.dict(os.environ, environ, clear=True):
            with self.assertRaises(ValueError):
                envmod.env_bool("FLAG", required=True)


class EnvListTests(SimpleTestCase):
    """CSRF_TRUSTED_ORIGINS / CORS_ALLOWED_ORIGINS whitespace handling."""

    def test_strips_each_element(self):
        # The exact shape that used to configure one origin and silently drop
        # the rest: no matching is done on the stripped value.
        with mock.patch.dict(
            os.environ, {"ORIGINS": "https://a.app, https://b.app,https://c.app"},
            clear=False,
        ):
            self.assertEqual(
                envmod.env_list("ORIGINS"),
                ["https://a.app", "https://b.app", "https://c.app"],
            )

    def test_drops_empty_elements(self):
        with mock.patch.dict(
            os.environ, {"ORIGINS": "https://a.app,,  ,https://b.app,"}, clear=False
        ):
            self.assertEqual(envmod.env_list("ORIGINS"), ["https://a.app", "https://b.app"])

    def test_unset_returns_the_default(self):
        environ = {k: v for k, v in os.environ.items() if k != "ORIGINS"}
        with mock.patch.dict(os.environ, environ, clear=True):
            self.assertEqual(envmod.env_list("ORIGINS"), [])
            self.assertEqual(envmod.env_list("ORIGINS", default=("x",)), ["x"])


class EnvIntTests(SimpleTestCase):
    def test_parses_and_bounds_check(self):
        with mock.patch.dict(os.environ, {"PORT": " 465 "}, clear=False):
            self.assertEqual(envmod.env_int("PORT", 587), 465)
        with mock.patch.dict(os.environ, {"PORT": "70000"}, clear=False):
            with self.assertRaises(ValueError):
                envmod.env_int("PORT", 587, minimum=1, maximum=65535)

    def test_non_numeric_raises(self):
        with mock.patch.dict(os.environ, {"PORT": "5-8-7"}, clear=False):
            with self.assertRaises(ValueError):
                envmod.env_int("PORT", 587)


class ProductionEmailValidationTests(SimpleTestCase):
    def test_a_complete_configuration_is_accepted(self):
        _settings_with()  # must not raise

    def test_the_console_backend_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            _settings_with(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
        self.assertIn("does not send mail", str(ctx.exception))

    def test_every_non_delivering_backend_is_rejected(self):
        # locmem in particular looks like a working backend in tests, which is
        # exactly how it reaches a production environment by accident.
        for backend in (
            "django.core.mail.backends.console.EmailBackend",
            "django.core.mail.backends.locmem.EmailBackend",
            "django.core.mail.backends.filebased.EmailBackend",
            "django.core.mail.backends.dummy.EmailBackend",
        ):
            with self.subTest(backend=backend):
                with self.assertRaises(ImproperlyConfigured):
                    _settings_with(EMAIL_BACKEND=backend)

    def test_all_problems_are_reported_at_once(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            _settings_with(
                EMAIL_HOST="",
                EMAIL_HOST_USER="",
                EMAIL_HOST_PASSWORD="",
                DEFAULT_FROM_EMAIL="",
            )
        message = str(ctx.exception)
        for expected in ("EMAIL_HOST is not set", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD",
                          "DEFAULT_FROM_EMAIL"):
            self.assertIn(expected, message)

    def test_credentials_are_never_echoed_in_the_error(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            _settings_with(DEFAULT_FROM_EMAIL="not-an-email")
        self.assertNotIn("SG.super-secret-value", str(ctx.exception))

    def test_tls_is_required_for_a_remote_host(self):
        # EMAIL_USE_TLS=false to a remote host sends credentials in cleartext.
        with self.assertRaises(ImproperlyConfigured) as ctx:
            _settings_with(EMAIL_USE_TLS=False, EMAIL_USE_SSL=False)
        self.assertIn("cleartext", str(ctx.exception))

    def test_ssl_without_tls_is_allowed_on_465(self):
        _settings_with(EMAIL_USE_TLS=False, EMAIL_USE_SSL=True, EMAIL_PORT=465)

    def test_ssl_on_a_non_ssl_port_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            _settings_with(EMAIL_USE_SSL=True, EMAIL_PORT=587)
        self.assertIn("465", str(ctx.exception))

    def test_tls_and_ssl_together_are_rejected(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            _settings_with(EMAIL_USE_TLS=True, EMAIL_USE_SSL=True)
        self.assertIn("both enabled", str(ctx.exception))

    def test_a_local_mta_needs_neither_tls_nor_credentials(self):
        _settings_with(
            EMAIL_HOST="localhost", EMAIL_HOST_USER="", EMAIL_HOST_PASSWORD="",
            EMAIL_USE_TLS=False,
        )

    def test_an_invalid_from_address_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured) as ctx:
            _settings_with(DEFAULT_FROM_EMAIL="nope@")
        self.assertIn("not a valid address", str(ctx.exception))

    def test_an_unrecognised_backend_is_rejected(self):
        with self.assertRaises(ImproperlyConfigured):
            _settings_with(EMAIL_BACKEND="mycompany.magicmail.send")


class ProductionBootTests(SimpleTestCase):
    """End-to-end: a misconfigured production process must refuse to start."""

    BASE_ENV = {
        "DJANGO_ENV": "production",
        "SECRET_KEY": "a-real-secret-not-the-placeholder-value",
        "ALLOWED_HOSTS": "securegate.example.com",
        # Production requires a PostgreSQL DATABASE_URL. Nothing here connects
        # -- the probe only imports settings -- but the guard runs at import, so
        # a sqlite URL would stop the boot before email validation is reached.
        "DATABASE_URL": "postgres://u:p@db.invalid:5432/securegate",
        # The QR signing key is checked earlier in settings.py; supply a valid
        # one so this test reaches the email validation instead of stopping at
        # an unrelated guard.
        "QR_SIGNING_KEY": "boot-check-qr-signing-key-not-a-secret",
        "EMAIL_HOST": "smtp.sendgrid.net",
        "EMAIL_PORT": "587",
        "EMAIL_USE_TLS": "true",
        "EMAIL_HOST_USER": "apikey",
        "EMAIL_HOST_PASSWORD": "SG.secret",
        "DEFAULT_FROM_EMAIL": "no-reply@securegate.test",
        "DJANGO_SETTINGS_MODULE": "config.settings",
    }

    def _boot(self, **env_overrides):
        """Import config.settings in a fresh process with this environment.

        ``None`` means "remove the variable entirely", which is how a missing
        variable is simulated -- setting it to "" would not exercise the
        "not set" branch of the guards.
        """
        # Start from a clean slate for anything this test controls, so an
        # ambient EMAIL_* in the developer's shell cannot make a guard pass or
        # fail spuriously.
        env = {k: v for k, v in os.environ.items() if not k.startswith("EMAIL_")}
        env.update(self.BASE_ENV)
        for key, value in env_overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = str(value)
        return subprocess.run(
            [sys.executable, "-c", "import config.settings"],
            capture_output=True, text=True, env=env, timeout=120,
        )

    def test_production_with_a_console_backend_refuses_to_boot(self):
        result = self._boot(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
        self.assertNotEqual(result.returncode, 0, "a console mailer must not boot in production")
        self.assertIn("does not send mail", result.stderr)

    def test_lowercase_tls_true_still_means_tls(self):
        # EMAIL_USE_TLS=true used to evaluate to False, so this boot only
        # succeeds if the value was parsed as TLS.
        self.assertEqual(self._boot().returncode, 0, self._boot().stderr)

    def test_production_without_credentials_refuses_to_boot(self):
        result = self._boot(EMAIL_HOST_USER=None, EMAIL_HOST_PASSWORD=None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EMAIL_HOST_USER", result.stderr)

    def test_production_without_tls_to_a_remote_host_refuses_to_boot(self):
        result = self._boot(EMAIL_USE_TLS="false")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cleartext", result.stderr)


class EmailProviderIsConfiguredTests(SimpleTestCase):
    """The old implementation was a tautology and always returned True."""


    def test_smtp_is_configured(self):
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            ENVIRONMENT="production",
            EMAIL_HOST="smtp.sendgrid.net",
            DEFAULT_FROM_EMAIL="no-reply@securegate.test",
        ):
            self.assertTrue(notifications.EmailProvider().is_configured())


class _RecordingMessage:
    """Stands in for an EmailMessage so deliver() can be tested directly."""

    def __init__(self, sent=1, raises=None):
        self._sent = sent
        self._raises = raises
        self.send_calls = 0

    def send(self, *args, **kwargs):
        self.send_calls += 1
        if self._raises is not None:
            raise self._raises
        return self._sent


class _RecordCollector(logging.Handler):
    """Captures LogRecords so tests can assert on the structured ``extra``.

    ``assertLogs`` only exposes the formatted message, but the point of the
    logging in ``deliver()`` is the structured fields (``event``,
    ``reference``, ``error_type``) that log aggregation alerts on.
    """

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    @property
    def text(self):
        """Everything a formatter could ever print, for leak assertions."""
        parts = []
        for record in self.records:
            parts.append(record.getMessage())
            parts.extend(f"{k}={v!r}" for k, v in record.__dict__.items())
        return " ".join(parts)

    def field(self, name):
        return [getattr(r, name, None) for r in self.records]


class DeliverTests(TestCase):
    """A send that reaches nobody must not be reported as a send."""

    def _capture(self, fn):
        collector = _RecordCollector()
        logger = logging.getLogger("visits.emails")
        logger.addHandler(collector)
        previous_level = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            result = fn()
        finally:
            logger.setLevel(previous_level)
            logger.removeHandler(collector)
        return result, collector

    def test_a_successful_send_is_reported_as_sent(self):
        message = _RecordingMessage(sent=1)
        result, _ = self._capture(
            lambda: deliver(message, event="email.test", reference="v1")
        )
        self.assertTrue(result.sent)
        self.assertFalse(result.skipped)
        self.assertIsNone(result.as_exception())

    def test_a_backend_returning_zero_is_a_failure(self):
        # The console, locmem, filebased and dummy backends all do this. It is
        # the failure mode that has no exception attached to it.
        result, records = self._capture(
            lambda: deliver(_RecordingMessage(sent=0), event="email.test", reference="v1")
        )
        self.assertFalse(result.sent)
        self.assertFalse(result.skipped)
        self.assertEqual(result.reason, "not_delivered")
        self.assertIn("ZeroMessagesSent", records.field("error_type"))
        self.assertIn("email.test", records.field("event"))
        self.assertIn("failed", records.field("outcome"))

    def test_a_raising_backend_is_a_failure(self):
        error = OSError("connection refused")
        result, records = self._capture(
            lambda: deliver(_RecordingMessage(raises=error), event="email.test")
        )
        self.assertFalse(result.sent)
        self.assertIs(result.error, error)
        self.assertEqual(result.error_type, "OSError")
        self.assertIsInstance(result.as_exception(), EmailDeliveryError)
        self.assertIn("OSError", records.field("error_type"))

    def test_deliver_never_raises(self):
        # Approval must survive a mailer outage.
        result, _ = self._capture(
            lambda: deliver(_RecordingMessage(raises=RuntimeError("smtp down")),
                            event="email.test")
        )
        self.assertFalse(result.sent)

    def test_the_failure_log_contains_no_recipient_body_or_secret(self):
        # The whole reason deliver() logs the exception *type* and not
        # str(exc): SMTP error text is written by the remote server and
        # routinely echoes the recipient back.
        _, records = self._capture(
            lambda: deliver(
                _RecordingMessage(
                    raises=OSError("auth failed for visitor@corp.test pw=hunter2")
                ),
                event="email.test",
                reference="visit-uuid",
            )
        )
        text = records.text
        self.assertIn("visit-uuid", text)      # the reference is what you need
        self.assertIn("OSError", text)         # the type is what you need
        self.assertNotIn("visitor@corp.test", text)
        self.assertNotIn("hunter2", text)

    def test_skipped_is_not_a_failure(self):
        result = DeliveryResult(skipped=True, reason="no_recipient")
        self.assertIsNone(result.as_exception())


class ApprovalEmailOutcomeTests(TestCase):
    """Approval must tell the operator which of the three things happened."""

    def setUp(self):
        from accounts.models import Role, User
        from organizations.models import Organization
        from visits.models import Visitor, Visit

        self.org = Organization.objects.create(name="Mail Co", slug="mail-co")
        self.building = self.org.buildings.create(name="HQ") if hasattr(
            self.org, "buildings"
        ) else None
        from organizations.models import Building

        self.building = Building.objects.create(organization=self.org, name="HQ")
        self.admin = User.objects.create_user(
            email="admin@mail.test", password="Str0ng!Pass", full_name="A",
            role=Role.ADMIN, organization=self.org,
        )
        self.visitor = Visitor.objects.create(
            organization=self.org, full_name="Ravi", phone="9999999999",
            email="ravi@corp.test",
        )
        self.visit = Visit.objects.create(
            visitor=self.visitor, organization=self.org, building=self.building,
            host=self.admin, created_by=self.admin, purpose="Interview",
        )
        from visits.services import approve_visit

        self.approve = approve_visit

    def test_success_reports_emailed(self):

        with mock.patch("visits.emails.deliver", return_value=DeliveryResult(sent=True)):
            ok, message = self.approve(self.visit, self.admin)
        self.assertTrue(ok)
        self.assertIn("emailed", message)

    def test_a_send_failure_is_reported_as_a_failure(self):
        with mock.patch(
            "visits.emails.deliver",
            return_value=DeliveryResult(reason="not_delivered"),
        ):
            ok, message = self.approve(self.visit, self.admin)
        # The pass is still valid, so the visit is still approved.
        self.assertTrue(ok)
        self.assertIn("FAILED", message)

    def test_a_missing_address_is_distinct_from_a_failure(self):
        self.visitor.email = ""
        self.visitor.save(update_fields=["email"])
        with mock.patch(
            "visits.emails.deliver", return_value=DeliveryResult(skipped=True, reason="no_recipient")
        ):
            ok, message = self.approve(self.visit, self.admin)
        self.assertTrue(ok)
        self.assertIn("no email address", message)
        self.assertNotIn("FAILED", message)


class ReminderSendOutcomeTests(TestCase):
    """A reminder the backend accepted and dropped must be recorded FAILED.

    Setup mirrors ``visits.tests.VisitReminderTests``: a pre-booking (which is
    what schedules the reminder rows) plus a simulated "now" of 20h before the
    slot, so the 24h trigger has passed and the 1h trigger has not. Driving off
    the wall clock instead makes the outcome depend on the time of day the
    suite happens to run.
    """

    def setUp(self):
        from accounts.models import User
        from organizations.models import Department, Employee, Organization
        from visits.reminders import send_due_visit_reminders, visit_slot_start
        from visits.services import create_pre_booking
        from visits.models import VisitType

        self.send_due = send_due_visit_reminders
        self.org = Organization.objects.create(
            name="Remind Co", slug="remind-co", timezone="UTC",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        self.dept = Department.objects.create(organization=self.org, name="Advisory")
        self.host = User.objects.create_user(
            email="host@remind.test", password="Passw0rd!123", full_name="H",
            organization=self.org,
        )
        Employee.objects.create(
            user=self.host, organization=self.org, employee_id="EMP-R1",
            department=self.dept, designation="Lead",
        )
        self.visitor_email = "guest@corp.test"
        visit, ok, message = create_pre_booking(
            self.org,
            visitor_data={
                "full_name": "Reminder Guest",
                "phone": "9888888888",
                "email": self.visitor_email,
            },
            visit_type=VisitType.CLIENT_MEETING,
            department_id=self.dept.pk,
            host_id=self.host.pk,
            visit_date=(timezone.localdate() + timedelta(days=2)).isoformat(),
            expected_arrival="10:00",
            expected_exit="10:30",
            purpose="Client Meeting",
        )
        self.assertTrue(ok, message)
        self.visit = visit
        # 24h before the slot has passed; 1h before has not.
        self.due_now = visit_slot_start(visit, self.org) - timedelta(hours=20)

    def _run(self, send_result):
        with mock.patch("django.core.mail.EmailMessage.send", return_value=send_result):
            return self.send_due(now=self.due_now)

    def test_the_fixture_actually_has_a_due_reminder(self):
        # Guards the setup itself: without this, every assertion below would
        # pass or fail on an all-zero summary for the wrong reason.
        summary = self._run(1)
        self.assertEqual(summary["attempted"], 1, summary)
        self.assertEqual(summary["sent"], 1, summary)

    def test_zero_sent_is_recorded_as_failed(self):
        # The console/locmem/filebased/dummy backends all return a delivery
        # count the caller used to ignore, so a dropped reminder was previously
        # written to the ledger as SENT.
        from visits.models import VisitReminder

        summary = self._run(0)
        self.assertEqual(summary["failed"], 1, summary)
        self.assertEqual(summary["sent"], 0, summary)
        row = self.visit.reminders.get(offset_hours=24)
        self.assertEqual(row.status, VisitReminder.Status.FAILED)

    def test_a_successful_reminder_is_still_recorded_as_sent(self):
        # Guards against the fix over-correcting into failing everything.
        from visits.models import VisitReminder

        summary = self._run(1)
        self.assertEqual(summary["failed"], 0, summary)
        row = self.visit.reminders.get(offset_hours=24)
        self.assertEqual(row.status, VisitReminder.Status.SENT)

    def test_the_reminder_audit_detail_holds_no_email_address(self):
        # The address is already reachable via visit.visitor; duplicating it
        # into a log table spreads visitor PII into a second store.
        from organizations.models import AuditLog

        self._run(1)
        entries = list(AuditLog.objects.filter(action="Visit reminder sent"))
        self.assertTrue(entries, "expected a 'Visit reminder sent' audit entry")
        for entry in entries:
            self.assertNotIn(self.visitor_email, entry.details)

    def test_a_smtp_error_echoing_the_recipient_is_scrubbed(self):
        # SMTP servers routinely include the address in their rejection text,
        # and that text is persisted on the reminder row.
        from visits.models import VisitReminder

        with mock.patch(
            "django.core.mail.EmailMessage.send",
            side_effect=OSError(f"550 mailbox unavailable: {self.visitor_email}"),
        ):
            summary = self.send_due(now=self.due_now)
        self.assertEqual(summary["failed"], 1, summary)
        row = self.visit.reminders.get(offset_hours=24)
        self.assertEqual(row.status, VisitReminder.Status.FAILED)
        self.assertNotIn(self.visitor_email, row.error)
        # The reason itself survives, so the row is still diagnosable.
        self.assertIn("OSError", row.error)

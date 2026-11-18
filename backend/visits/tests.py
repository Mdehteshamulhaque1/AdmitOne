import io
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.core.management import call_command
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Role
from accounts.permissions import has_perm
from accounts.utils import org_localdate
from organizations.models import AuditLog, Building, Department, Employee, Organization

from visits.arrival import can_mark_arriving, mark_visitor_arriving
from visits.models import (
    Blacklist,
    QRPass,
    Visit,
    VisitNotification,
    VisitReminder,
    VisitStatus,
    VisitType,
    Visitor,
)
from visits.reminders import send_due_visit_reminders
from visits.services import (
    approve_visit,
    check_in,
    check_out,
    create_pre_booking,
    get_or_create_visitor,
    register_visit,
    reject_visit,
    reissue_qr_pass,
)

User = get_user_model()


class SecureGateTestCase(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Co", slug="test-co")
        self.dept = Department.objects.create(organization=self.org, name="Engineering")
        self.building = Building.objects.create(organization=self.org, name="HQ", floors=3)

        self.admin = User.objects.create_user(
            email="admin@test.com", password="Passw0rd!123",
            full_name="Divya Admin", role=Role.ADMIN, organization=self.org,
        )
        self.security = User.objects.create_user(
            email="security@test.com", password="Passw0rd!123",
            full_name="Arvind Kumar", role=Role.SECURITY, organization=self.org,
        )
        self.reception = User.objects.create_user(
            email="reception@test.com", password="Passw0rd!123",
            full_name="Rahul Verma", role=Role.RECEPTIONIST, organization=self.org,
        )
        Employee.objects.create(
            user=self.admin, organization=self.org, employee_id="EMP-1",
            department=self.dept, designation="Head of Administration",
        )
        self.visitor = Visitor.objects.create(
            full_name="Ravi Kumar", phone="9999999999", company="Acme",
            organization=self.org,
        )

    def register_visit(self):
        return Visit.objects.create(
            visitor=self.visitor, organization=self.org, building=self.building,
            host=self.admin, created_by=self.reception,
            purpose="Interview", visit_date=timezone.localdate(),
        )


class VisitWorkflowTests(SecureGateTestCase):
    def test_full_workflow_registered_to_checked_out(self):
        visit = self.register_visit()
        self.assertEqual(visit.status, VisitStatus.PENDING)

        ok, _ = approve_visit(visit, self.admin)
        self.assertTrue(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertTrue(hasattr(visit, "qr_pass"))
        self.assertTrue(visit.qr_pass.is_valid)

        ok, _ = check_in(visit, self.security, via_qr=True)
        self.assertTrue(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_IN)
        self.assertTrue(visit.qr_pass.is_used)

        ok, _ = check_out(visit, self.security)
        self.assertTrue(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_OUT)
        self.assertGreaterEqual(visit.duration_minutes, 0)

    def test_cannot_check_in_twice(self):
        visit = self.register_visit()
        approve_visit(visit, self.admin)
        check_in(visit, self.security)
        ok, _ = check_in(visit, self.security)
        self.assertFalse(ok)

    def test_reject_workflow(self):
        visit = self.register_visit()
        ok, _ = reject_visit(visit, self.admin, "Not needed")
        self.assertTrue(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.REJECTED)
        self.assertFalse(hasattr(visit, "qr_pass"))

    def test_approval_blocked_for_blacklisted_visitor(self):
        from visits.models import Blacklist
        Blacklist.objects.create(visitor=self.visitor, reason="PERMANENT_BAN", added_by=self.reception)
        visit = self.register_visit()
        ok, msg = approve_visit(visit, self.admin)
        self.assertFalse(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.PENDING)


class QRPassTests(SecureGateTestCase):
    def test_qr_verification_cycle(self):
        visit = self.register_visit()
        approve_visit(visit, self.admin)
        qr = visit.qr_pass

        ok, msg, found = QRPass.verify(str(qr.token), qr.signature)
        self.assertTrue(ok, msg)
        self.assertEqual(found.pk, qr.pk)

        ok, msg, _ = QRPass.verify(str(qr.token), "x" * 64)
        self.assertFalse(ok)
        self.assertIn("tampered", msg)

        ok, msg, _ = QRPass.verify("00000000-0000-0000-0000-000000000000", "x" * 64)
        self.assertFalse(ok)

        check_in(visit, self.security, via_qr=True)
        ok, msg, _ = QRPass.verify(str(qr.token), qr.signature)
        self.assertFalse(ok)
        self.assertIn("duplicate", msg)


class QRPassEmailTests(SecureGateTestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_approval_emails_qr_pass_to_visitor(self):
        from django.core import mail

        self.visitor.email = "visitor@gmail.com"
        self.visitor.save()
        visit = self.register_visit()

        ok, msg = approve_visit(visit, self.admin)
        self.assertTrue(ok)
        self.assertIn("emailed", msg)

        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, ["visitor@gmail.com"])
        self.assertIn("QR pass", email.subject)
        self.assertIn(visit.visitor.full_name, email.body)
        self.assertEqual(len(email.attachments), 1)
        attachment = email.attachments[0]
        if isinstance(attachment, tuple):
            self.assertTrue(attachment[1].startswith(b"\x89PNG"))
        else:
            self.assertEqual(attachment.get_content_type(), "image/png")
            self.assertTrue(attachment.get_payload(decode=True).startswith(b"\x89PNG"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_no_email_when_visitor_has_no_address(self):
        from django.core import mail

        visit = self.register_visit()
        ok, _ = approve_visit(visit, self.admin)
        self.assertTrue(ok)
        self.assertEqual(len(mail.outbox), 0)


class RBACTests(SecureGateTestCase):
    def test_role_permissions(self):
        self.assertTrue(has_perm(self.admin, "scan_qr"))
        self.assertTrue(has_perm(self.admin, "approve_visitor"))
        self.assertTrue(has_perm(self.admin, "manage_buildings"))
        self.assertTrue(has_perm(self.reception, "badge_print"))
        self.assertTrue(has_perm(self.reception, "create_visitor"))
        self.assertFalse(has_perm(self.reception, "scan_qr"))
        self.assertFalse(has_perm(self.reception, "approve_visitor"))
        self.assertTrue(has_perm(self.security, "scan_qr"))
        self.assertTrue(has_perm(self.security, "checkin_visitor"))
        self.assertFalse(has_perm(self.security, "badge_print"))
        self.assertFalse(has_perm(self.security, "approve_visitor"))

    def test_account_lockout(self):
        from django.conf import settings
        self.assertFalse(self.admin.is_locked)
        for _ in range(settings.MAX_LOGIN_ATTEMPTS):
            self.admin.register_failed_attempt(settings)
        self.assertTrue(self.admin.is_locked)


class OrganizationIsolationTests(SecureGateTestCase):
    """Cross-tenant guards live in the service and must refuse foreign orgs."""

    def setUp(self):
        super().setUp()
        self.other_org = Organization.objects.create(name="Rival Co", slug="rival-co")
        self.other_security = User.objects.create_user(
            email="other-security@test.com", password="Passw0rd!123",
            full_name="Eve Guard", role=Role.SECURITY, organization=self.other_org,
        )
        self.other_admin = User.objects.create_user(
            email="other-admin@test.com", password="Passw0rd!123",
            full_name="Bob Admin", role=Role.ADMIN, organization=self.other_org,
        )

    def test_foreign_officer_cannot_check_in(self):
        visit = self.register_visit()
        approve_visit(visit, self.admin)
        ok, msg = check_in(visit, self.other_security, via_qr=True)
        self.assertFalse(ok)
        self.assertIn("do not have access", msg)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)

    def test_foreign_admin_cannot_approve(self):
        visit = self.register_visit()
        ok, msg = approve_visit(visit, self.other_admin)
        self.assertFalse(ok)
        self.assertIn("do not have access", msg)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.PENDING)

    def test_foreign_officer_cannot_check_out(self):
        visit = self.register_visit()
        approve_visit(visit, self.admin)
        check_in(visit, self.security, via_qr=True)
        ok, _ = check_out(visit, self.other_security)
        self.assertFalse(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_IN)


class LifecycleBoundaryTests(SecureGateTestCase):
    """Reject invalid state transitions at the service boundary."""

    def test_rejected_visit_cannot_check_in(self):
        visit = self.register_visit()
        reject_visit(visit, self.admin, "Busy")
        ok, msg = check_in(visit, self.security, via_qr=True)
        self.assertFalse(ok)
        self.assertIn("Cannot check in", msg)

    def test_pending_visit_cannot_check_out(self):
        visit = self.register_visit()
        ok, msg = check_out(visit, self.security)
        self.assertFalse(ok)
        self.assertIn("Cannot check out", msg)

    def test_checked_out_visit_cannot_check_in_again(self):
        visit = self.register_visit()
        approve_visit(visit, self.admin)
        check_in(visit, self.security, via_qr=True)
        check_out(visit, self.security)
        ok, _ = check_in(visit, self.security)
        self.assertFalse(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_OUT)

    def test_approved_visit_cannot_be_approved_twice(self):
        visit = self.register_visit()
        approve_visit(visit, self.admin)
        ok, msg = approve_visit(visit, self.admin)
        self.assertFalse(ok)

    def test_check_in_blocked_for_blacklisted_visitor(self):
        visit = self.register_visit()
        approve_visit(visit, self.admin)
        Blacklist.objects.create(
            visitor=self.visitor, reason="PERMANENT_BAN", added_by=self.reception,
        )
        ok, msg = check_in(visit, self.security, via_qr=True)
        self.assertFalse(ok)
        self.assertIn("blacklisted", msg)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)


class QRExpiryAndReplayTests(SecureGateTestCase):
    """Expired and reused passes must be rejected."""

    def test_expired_pass_is_rejected(self):
        visit = self.register_visit()
        approve_visit(visit, self.admin)
        QRPass.objects.filter(pk=visit.qr_pass.pk).update(
            expires_at=timezone.now() - timezone.timedelta(minutes=5),
        )
        ok, msg, found = QRPass.verify(
            str(visit.qr_pass.token), visit.qr_pass.signature,
        )
        self.assertFalse(ok)
        self.assertIn("expired", msg)

    def test_used_pass_cannot_reenable_checkin(self):
        visit = self.register_visit()
        approve_visit(visit, self.admin)
        QRPass.objects.filter(pk=visit.qr_pass.pk).update(is_used=True)
        ok, msg = check_in(visit, self.security, via_qr=True)
        self.assertFalse(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)


class RegistrationServiceTests(SecureGateTestCase):
    """Shared registration service: dedup, timezone, validation."""

    def setUp(self):
        super().setUp()
        self.other_org = Organization.objects.create(name="Second Co", slug="second-co")
        self.other_admin = User.objects.create_user(
            email="second-admin@test.com", password="Passw0rd!123",
            full_name="Sana Real", role=Role.ADMIN, organization=self.other_org,
        )

    def test_dedup_is_scoped_to_organization(self):
        visit1, ok, _ = register_visit(
            self.admin,
            visitor_data={"full_name": "Ravi Kumar", "phone": "9999999999"},
            purpose="First",
            expected_arrival="10:00",
            expected_exit="11:00",
        )
        self.assertTrue(ok)
        v2, created = get_or_create_visitor(
            self.org, full_name="Ravi Kumar", phone="9999999999",
        )
        self.assertFalse(created)
        self.assertEqual(visit1.visitor.pk, v2.pk)

    def test_same_phone_in_different_org_gets_own_visitor(self):
        visit1, ok, _ = register_visit(
            self.admin,
            visitor_data={"full_name": "Ravi Kumar", "phone": "9999999999"},
            purpose="First",
            expected_arrival="10:00",
            expected_exit="11:00",
        )
        self.assertTrue(ok)
        v2, created = get_or_create_visitor(
            self.other_org, full_name="Ravi Kumar", phone="9999999999",
        )
        self.assertTrue(created)
        self.assertNotEqual(visit1.visitor.pk, v2.pk)

    def test_register_rejects_exit_before_arrival(self):
        visit, ok, msg = register_visit(
            self.admin,
            visitor=self.visitor,
            purpose="Meeting",
            expected_arrival="14:00",
            expected_exit="09:00",
        )
        self.assertFalse(ok)
        self.assertIsNone(visit)

    def test_register_rejects_foreign_host(self):
        visit, ok, msg = register_visit(
            self.admin,
            visitor=self.visitor,
            purpose="Meeting",
            host_id=self.other_admin.pk,
        )
        self.assertFalse(ok)
        self.assertIn("Host must belong", str(msg))

    def test_register_creates_pending_visit_and_audits_with_ip(self):
        visit, ok, msg = register_visit(
            self.admin,
            visitor=self.visitor,
            purpose="Meeting",
            expected_arrival="10:00",
            expected_exit="11:00",
            audit_ip="203.0.113.7",
        )
        self.assertTrue(ok)
        self.assertEqual(visit.status, VisitStatus.PENDING)
        log = AuditLog.objects.filter(
            entity_type="Visit", action__icontains="Visit registered",
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.ip_address, "203.0.113.7")

    def test_walkin_auto_approves_and_issues_qr(self):
        visit, ok, msg = register_visit(
            self.reception,
            visitor=self.visitor,
            purpose="Walk-in",
            expected_arrival="10:00",
            expected_exit="12:00",
            walkin=True,
        )
        self.assertTrue(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertTrue(hasattr(visit, "qr_pass"))

    def test_org_localdate_uses_org_timezone(self):
        from datetime import datetime, timezone as dtz

        Organization.objects.filter(pk=self.org.pk).update(timezone="Asia/Kolkata")
        self.org.refresh_from_db()
        when = datetime(2026, 1, 1, 23, 30, tzinfo=dtz.utc)
        local = org_localdate(self.admin, when=when)
        self.assertEqual(local, datetime(2026, 1, 2).date())


class SecurityFixRegressionTests(SecureGateTestCase):
    """Regression tests for the security-audit findings (approval bypass,
    input-validation 500s, blacklist-removal privilege, malformed QR)."""

    def test_qr_check_in_blocks_unapproved_visit(self):
        visit = self.register_visit()  # PENDING
        QRPass.issue(visit)  # simulate a badge minted before approval
        ok, msg = check_in(visit, self.security, via_qr=True)
        self.assertFalse(ok, msg)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.PENDING)


    def test_malformed_qr_token_returns_false_not_500(self):
        ok, msg, qr = QRPass.verify("garbage!!!-not-a-uuid", "abc")
        self.assertFalse(ok)
        self.assertIsNone(qr)

    def test_register_rejects_invalid_visit_date(self):
        visit, ok, msg = register_visit(
            self.admin,
            visitor_data={"full_name": "Xeka", "phone": "7000000200"},
            purpose="M",
            visit_date="not-a-date",
        )
        self.assertIsNone(visit)
        self.assertFalse(ok)
        self.assertIn("visit", msg.get("detail", {}))

    def test_register_rejects_oversized_purpose(self):
        visit, ok, msg = register_visit(
            self.admin,
            visitor_data={"full_name": "Xeka", "phone": "7000000201"},
            purpose="A" * 201,
        )
        self.assertIsNone(visit)
        self.assertFalse(ok)

    def test_register_coerces_non_string_notes(self):
        visit, ok, msg = register_visit(
            self.admin,
            visitor_data={"full_name": "Xeka", "phone": "7000000202"},
            purpose="M",
            notes=["not", "a", "string"],
        )
        self.assertTrue(ok, msg)
        self.assertEqual(visit.notes, "['not', 'a', 'string']")

    def test_reject_visit_rejects_oversized_reason(self):
        visit = self.register_visit()
        ok, msg = reject_visit(visit, self.admin, reason="R" * 301)
        self.assertFalse(ok)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.PENDING)


class VisitStatusEnumTests(SecureGateTestCase):
    """Pins the compact Visit status set.

    EXPIRED was deliberately removed from the domain model: QR pass expiry is a
    QRPass property (expires_at / is_expired), never a Visit state, and no code
    ever transitioned a Visit to EXPIRED. This test guards against a dead enum
    state silently reappearing.
    """

    def test_status_enum_has_no_dead_expired_state(self):
        self.assertEqual(
            set(VisitStatus.values),
            {"PENDING", "APPROVED", "REJECTED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED", "ARCHIVED"},
        )

    def test_archive_remains_the_only_post_checkout_terminal_path(self):
        visit = self.register_visit()
        self.assertTrue(approve_visit(visit, self.admin)[0])
        self.assertTrue(check_in(visit, self.security)[0])
        self.assertTrue(check_out(visit, self.security)[0])
        Visit.objects.filter(pk=visit.pk).update(
            checked_out_at=timezone.now() - timezone.timedelta(days=60)
        )

        from visits.services import archive_old_visits

        archive_old_visits(organization=self.org)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.ARCHIVED)


class VisitReminderTests(TestCase):
    """Feature #5 — automatic visit reminders (24h / 1h before, configurable)."""

    def setUp(self):
        self.org = Organization.objects.create(
            name="Reminder Co", slug="reminder-co", timezone="UTC",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        self.dept = Department.objects.create(organization=self.org, name="Advisory")
        self.host_user = User.objects.create_user(
            email="host@reminder.co", password="Passw0rd!123",
            full_name="Host Lead", organization=self.org,
        )
        Employee.objects.create(
            user=self.host_user, organization=self.org,
            employee_id="EMP-R1", department=self.dept, designation="Lead",
        )
        self.admin = User.objects.create_user(
            email="admin@reminder.co", password="Passw0rd!123",
            full_name="Rem Admin", role=Role.ADMIN, organization=self.org,
        )
        self.security = User.objects.create_user(
            email="sec@reminder.co", password="Passw0rd!123",
            full_name="Rem Sec", role=Role.SECURITY, organization=self.org,
        )
        self.today = timezone.localdate()
        self.slot_day = self.today + timedelta(days=2)

    def _book(self, phone="1111111111", email="guest@example.com", day=None):
        day = day or self.slot_day
        visit, ok, msg = create_pre_booking(
            self.org,
            visitor_data={
                "full_name": "Reminder Guest",
                "phone": phone,
                "email": email,
            },
            visit_type=VisitType.CLIENT_MEETING,
            department_id=self.dept.pk,
            host_id=self.host_user.pk,
            visit_date=day.isoformat(),
            expected_arrival="10:00",
            expected_exit="10:30",
            purpose="Client Meeting",
        )
        self.assertTrue(ok, msg)
        return visit

    def _slot_start(self, visit):
        from visits.reminders import visit_slot_start

        return visit_slot_start(visit, self.org)

    # -- scheduling ---------------------------------------------------

    def test_default_offsets_24_and_1_are_scheduled(self):
        visit = self._book()
        rows = list(visit.reminders.order_by("offset_hours"))
        self.assertEqual([r.offset_hours for r in rows], [1, 24])
        slot = self._slot_start(visit)
        for row in rows:
            self.assertEqual(
                row.trigger_at, slot - timezone.timedelta(hours=row.offset_hours)
            )
            self.assertEqual(row.status, VisitReminder.Status.PENDING)

    def test_reminder_offsets_are_configurable_per_org(self):
        self.org.visitor_policies = {"reminder_offsets_hours": [48]}
        self.org.save()
        visit = self._book(day=self.today + timedelta(days=3))
        rows = list(visit.reminders.all())
        self.assertEqual([r.offset_hours for r in rows], [48])

    @patch("django.utils.timezone.now")
    def test_offset_already_passed_is_not_scheduled(self, mocked_now):
        # A reminder whose trigger time has already elapsed must not be
        # scheduled when the booking is made.
        #
        # The clock is pinned because the outcome is inherently relative to
        # "now". Previously this booked a visit arriving *today at 10:00* with
        # the default 1h offset, whose trigger is 09:00 today -- so the
        # assertion only held when the suite happened to run after 09:00 local,
        # and the test failed for the other ~9 hours of the day. Freezing at
        # 12:00 on a fixed date and booking two days out with a 48h offset puts
        # the trigger a full day in the past, whatever the wall clock says.
        frozen = datetime(2026, 3, 2, 12, 0, tzinfo=dt_timezone.utc)
        mocked_now.return_value = frozen

        self.org.visitor_policies = {"reminder_offsets_hours": [48]}
        self.org.save()
        visit = self._book(day=(frozen + timedelta(days=2)).date())

        self.assertEqual(visit.reminders.count(), 0)

    def test_old_visits_are_never_backfilled(self):
        self.assertEqual(VisitReminder.objects.count(), 0)

    # -- due / delivery -------------------------------------------------

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_reminder_is_sent_when_trigger_passes(self):
        from django.core import mail

        visit = self._book()
        row = visit.reminders.get(offset_hours=24)
        # now = 20h before start: 24h trigger has passed, 1h has not.
        now = self._slot_start(visit) - timezone.timedelta(hours=20)
        summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(summary["attempted"], 1)
        row.refresh_from_db()
        self.assertEqual(row.status, VisitReminder.Status.SENT)
        self.assertIsNotNone(row.sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["guest@example.com"])
        self.assertIn(self.org.name, mail.outbox[0].subject)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_reminder_not_sent_before_trigger(self):
        from django.core import mail

        visit = self._book()
        now = self._slot_start(visit) - timezone.timedelta(hours=30)
        summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["attempted"], 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(
            visit.reminders.filter(status=VisitReminder.Status.PENDING).count(), 2
        )

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_multiple_reminders_all_sent_when_due(self):
        from django.core import mail

        visit = self._book()
        now = self._slot_start(visit) - timezone.timedelta(hours=1)
        summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["sent"], 2)
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_skipped_when_visitor_has_no_email(self):

        visit = self._book(email="")
        now = self._slot_start(visit) - timezone.timedelta(hours=20)
        summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["sent"], 0)
        self.assertEqual(summary["skipped"], 1)
        row = visit.reminders.get(offset_hours=24)
        self.assertEqual(row.status, VisitReminder.Status.SKIPPED)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_duplicate_prevention_unique_per_offset(self):
        from django.core import mail

        visit = self._book()
        self.assertEqual(visit.reminders.count(), 2)
        now = self._slot_start(visit) - timezone.timedelta(hours=20)
        send_due_visit_reminders(now=now)
        send_due_visit_reminders(now=now + timezone.timedelta(minutes=1))
        self.assertEqual(visit.reminders.count(), 2)
        self.assertEqual(len(mail.outbox), 1, "a reminder must send once only")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_provider_failure_recorded_without_corrupting_visit(self):
        from django.core import mail

        visit = self._book()
        now = self._slot_start(visit) - timezone.timedelta(hours=20)

        with patch(
            "django.core.mail.EmailMessage.send",
            side_effect=Exception("SMTP down"),
        ):
            summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(len(mail.outbox), 0)
        row = visit.reminders.get(offset_hours=24)
        self.assertEqual(row.status, VisitReminder.Status.FAILED)
        self.assertIn("SMTP down", row.error)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.PENDING)
        self.assertTrue(
            AuditLog.objects.filter(action="Visit reminder failed").exists()
        )

    # -- ineligible visits ------------------------------------------------


    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_rejected_visit_is_not_reminded(self):
        from django.core import mail

        visit = self._book()
        ok, msg = reject_visit(visit, self.admin, reason="Full")
        self.assertTrue(ok, msg)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.REJECTED)
        now = self._slot_start(visit) - timezone.timedelta(hours=20)
        summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["sent"], 0)
        self.assertEqual(summary["ineligible"], 1)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_checked_in_visit_is_not_reminded(self):
        from django.core import mail

        visit = self._book()
        ok, msg = approve_visit(visit, self.admin)
        self.assertTrue(ok, msg)
        visit.refresh_from_db()
        ok2, msg2 = check_in(visit, self.security)
        self.assertTrue(ok2, msg2)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_IN)
        now = self._slot_start(visit) - timezone.timedelta(hours=20)
        before = len(mail.outbox)  # the approval step emails the QR pass.
        summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["sent"], 0)
        self.assertEqual(summary["ineligible"], 1)
        self.assertEqual(len(mail.outbox), before, "no reminder email may be added")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_visit_already_started_is_not_reminded(self):
        from django.core import mail

        visit = self._book()
        now = self._slot_start(visit) + timezone.timedelta(minutes=5)
        summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["sent"], 0)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_organization_timezone_is_respected(self):
        from django.core import mail

        self.org.timezone = "Asia/Kolkata"  # UTC+5:30
        self.org.save()
        visit = self._book()
        slot = self._slot_start(visit)
        self.assertEqual(slot.utcoffset().total_seconds() / 3600, 5.5)
        # Trigger at 24h before 10:00 IST today+2 = 10:00 IST today+1.
        trigger = visit.reminders.get(offset_hours=24).trigger_at
        self.assertEqual(trigger, slot - timezone.timedelta(hours=24))
        # An instant one hour before the slot (IST) is past both triggers.
        now = slot - timezone.timedelta(hours=1)
        summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["sent"], 2)
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
    )
    def test_organization_isolation(self):
        from django.core import mail

        other = Organization.objects.create(
            name="Other Reminder Co", slug="other-reminder-co", timezone="UTC",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        other_dept = Department.objects.create(organization=other, name="Eng")
        other_host = User.objects.create_user(
            email="ohost@other.co", password="Passw0rd!123",
            full_name="Other Host", organization=other,
        )
        Employee.objects.create(
            user=other_host, organization=other, employee_id="EMP-O1",
            department=other_dept, designation="Lead",
        )
        visit_a = self._book()
        visit_b, ok, _ = create_pre_booking(
            other,
            visitor_data={"full_name": "Other Guest", "phone": "2222222222", "email": "og@other.co"},
            visit_type=VisitType.CLIENT_MEETING,
            department_id=other_dept.pk,
            host_id=other_host.pk,
            visit_date=(self.slot_day + timedelta(days=10)).isoformat(),
            expected_arrival="10:00",
            expected_exit="10:30",
            purpose="Client Meeting",
        )
        self.assertTrue(ok)
        # Org B's slot is ten days later, so its reminders are NOT due when A's is.
        slot_a = self._slot_start(visit_a)
        now = slot_a - timezone.timedelta(hours=20)
        summary = send_due_visit_reminders(now=now)
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["guest@example.com"])
        self.assertEqual(visit_b.reminders.filter(status=VisitReminder.Status.PENDING).count(), 2)
        # A much later sweep picks B's reminders up independently.
        slot_b = self._slot_start(visit_b)
        summary_b = send_due_visit_reminders(now=slot_b - timezone.timedelta(hours=20))
        self.assertEqual(summary_b["sent"], 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["og@other.co"])


    # -- dry run / regression --------------------------------------------

    def test_dry_run_reports_without_sending(self):
        visit = self._book()
        now = self._slot_start(visit) - timezone.timedelta(hours=20)
        summary = send_due_visit_reminders(now=now, dry_run=True)
        self.assertEqual(summary["sent"], 1)
        self.assertEqual(
            visit.reminders.filter(status=VisitReminder.Status.PENDING).count(), 2
        )

    def test_existing_approval_qr_workflow_regression(self):
        visit = self._book()
        self.assertTrue(approve_visit(visit, self.admin)[0])
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertTrue(hasattr(visit, "qr_pass"))
        self.assertTrue(check_in(visit, self.security)[0])
        self.assertTrue(check_out(visit, self.security)[0])
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_OUT)


class VisitorArrivingTests(TestCase):
    """Feature #6 — visitor "I'm Arriving" signal from the portal."""

    def setUp(self):
        self.org = Organization.objects.create(
            name="Arrive Co", slug="arrive-co", timezone="UTC",
            working_hours_start="09:00", working_hours_end="18:00",
        )
        self.dept = Department.objects.create(organization=self.org, name="Ops")
        self.host_user = User.objects.create_user(
            email="host@arrive.co", password="Passw0rd!123",
            full_name="Host Lead", organization=self.org,
        )
        Employee.objects.create(
            user=self.host_user, organization=self.org,
            employee_id="EMP-A1", department=self.dept, designation="Ops Lead",
        )
        self.admin = User.objects.create_user(
            email="admin@arrive.co", password="Passw0rd!123",
            full_name="Arr Admin", role=Role.ADMIN, organization=self.org,
        )
        self.security = User.objects.create_user(
            email="sec@arrive.co", password="Passw0rd!123",
            full_name="Arr Sec", role=Role.SECURITY, organization=self.org,
        )
        self.today = timezone.localdate()
        self.slot_day = self.today + timedelta(days=1)

    def _book(self, phone="3333333333", email="arriver@example.com"):
        visit, ok, msg = create_pre_booking(
            self.org,
            visitor_data={"full_name": "Arriving Guest", "phone": phone, "email": email},
            visit_type=VisitType.CLIENT_MEETING,
            department_id=self.dept.pk,
            host_id=self.host_user.pk,
            visit_date=self.slot_day.isoformat(),
            expected_arrival="10:00",
            expected_exit="10:30",
            purpose="Client Meeting",
        )
        self.assertTrue(ok, msg)
        return visit

    def _approved(self, phone="3333333333", email="arriver@example.com"):
        visit = self._book(phone, email)
        self.assertTrue(approve_visit(visit, self.admin)[0])
        visit.refresh_from_db()
        return visit

    @staticmethod
    def _session(visitor, org):
        """The (organization, visitor) scope the arrival service expects --
        what a signed-in visitor account resolves to for one of its visits."""
        from types import SimpleNamespace

        return SimpleNamespace(
            organization=org, organization_id=org.pk, visitor=visitor, visitor_id=visitor.pk
        )


    def _slot_start(self, visit):
        from visits.reminders import visit_slot_start

        return visit_slot_start(visit, self.org)

    def test_valid_arriving_action(self):
        from django.core import mail

        visit = self._approved()
        now = self._slot_start(visit) - timedelta(minutes=10)
        updated, ok, message = mark_visitor_arriving(
            self._session(visit.visitor, self.org), visit, now=now
        )
        self.assertTrue(ok, message)
        updated.refresh_from_db()
        self.assertEqual(updated.arriving_at, now)
        self.assertEqual(updated.arriving_source, "PORTAL")
        self.assertEqual(updated.status, VisitStatus.APPROVED)
        self.assertTrue(
            AuditLog.objects.filter(action="Visitor marked arriving", entity_id=str(visit.visit_id)).exists()
        )
        notification = VisitNotification.objects.get(visit=visit, event="arriving")
        self.assertEqual(notification.status, VisitNotification.Status.SENT)
        self.assertEqual(notification.recipient, "host@arrive.co")
        subjects = [m.subject for m in mail.outbox]
        self.assertTrue(any("is arriving" in s for s in subjects), subjects)

    def test_arriving_does_not_check_in_and_qr_still_works(self):
        visit = self._approved()
        now = self._slot_start(visit) - timedelta(minutes=10)
        updated, ok, _ = mark_visitor_arriving(
            self._session(visit.visitor, self.org), visit, now=now
        )
        self.assertTrue(ok)
        updated.refresh_from_db()
        self.assertIsNone(updated.checked_in_at)
        self.assertTrue(updated.qr_pass.is_valid)
        self.assertTrue(check_in(updated, self.security, via_qr=True)[0])
        updated.refresh_from_db()
        self.assertEqual(updated.status, VisitStatus.CHECKED_IN)
        self.assertTrue(check_out(updated, self.security)[0])

    def test_ownership_mismatch_blocked(self):
        visit = self._approved()
        other_visitor = Visitor.objects.create(full_name="Other", phone="4444444444")
        updated, ok, message = mark_visitor_arriving(
            self._session(other_visitor, self.org),
            visit,
            now=self._slot_start(visit) - timedelta(minutes=10),
        )
        self.assertFalse(ok)
        self.assertIn("Unable to access", message)
        self.assertFalse(AuditLog.objects.filter(action="Visitor marked arriving").exists())

    def test_org_isolation_blocked(self):
        visit = self._approved()
        other_org = Organization.objects.create(name="Other", slug="other-arrive")
        session = self._session(visit.visitor, other_org)
        updated, ok, message = mark_visitor_arriving(
            session, visit, now=self._slot_start(visit) - timedelta(minutes=10)
        )
        self.assertFalse(ok)

    def test_requires_approved_status(self):
        visit = self._book()
        updated, ok, message = mark_visitor_arriving(
            self._session(visit.visitor, self.org),
            visit,
            now=self._slot_start(visit) - timedelta(minutes=10),
        )
        self.assertFalse(ok)
        self.assertIn("approved", message)


    def test_repeated_request_blocked(self):
        visit = self._approved()
        now = self._slot_start(visit) - timedelta(minutes=10)
        session = self._session(visit.visitor, self.org)
        self.assertTrue(mark_visitor_arriving(session, visit, now=now)[1])
        updated, ok, message = mark_visitor_arriving(session, visit, now=now)
        self.assertFalse(ok)
        self.assertIn("already", message)
        self.assertEqual(
            VisitNotification.objects.filter(visit=visit, event="arriving").count(), 1
        )
        self.assertEqual(
            AuditLog.objects.filter(action="Visitor marked arriving", entity_id=str(visit.visit_id)).count(),
            1,
        )

    def test_outside_window_too_early(self):
        visit = self._approved()
        now = self._slot_start(visit) - timedelta(hours=2)
        updated, ok, message = mark_visitor_arriving(
            self._session(visit.visitor, self.org), visit, now=now
        )
        self.assertFalse(ok)
        self.assertIn("Too early", message)

    def test_outside_window_after_arrival_time(self):
        visit = self._approved()
        now = self._slot_start(visit) + timedelta(minutes=1)
        updated, ok, message = mark_visitor_arriving(
            self._session(visit.visitor, self.org), visit, now=now
        )
        self.assertFalse(ok)
        self.assertIn("window has passed", message)

    def test_can_mark_arriving_helper(self):
        from visits.reminders import visit_slot_start

        visit = self._book()
        slot = visit_slot_start(visit, self.org)
        self.assertFalse(can_mark_arriving(visit, slot - timedelta(hours=2))[0])
        approve_visit(visit, self.admin)
        visit.refresh_from_db()
        allowed, _ = can_mark_arriving(visit, slot - timedelta(minutes=10))
        self.assertTrue(allowed)
        mark_visitor_arriving(
            self._session(visit.visitor, self.org), visit,
            now=slot - timedelta(minutes=10),
        )
        visit.refresh_from_db()
        self.assertFalse(can_mark_arriving(visit, slot - timedelta(minutes=10))[0])

    def test_host_without_email_gets_no_false_delivery(self):
        visit = self._approved()
        visit.host.email = ""
        visit.host.save()
        now = self._slot_start(visit) - timedelta(minutes=10)
        updated, ok, message = mark_visitor_arriving(
            self._session(visit.visitor, self.org), visit, now=now
        )
        self.assertTrue(ok, message)
        self.assertFalse(
            VisitNotification.objects.filter(visit=visit, event="arriving", status=VisitNotification.Status.SENT).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="Host arriving notification not delivered",
entity_id=str(visit.visit_id),
            ).exists()
        )


class ReissueServiceTests(SecureGateTestCase):
    """visits.services.reissue_qr_pass rotates the signed pass."""

    def setUp(self):
        super().setUp()
        self.visit = self.register_visit()
        ok, _ = approve_visit(self.visit, self.admin)
        self.assertTrue(ok)
        self.visit.refresh_from_db()

    def test_reissue_needs_approved_visit(self):
        pending = self.register_visit()
        ok, msg = reissue_qr_pass(pending, self.admin)
        self.assertFalse(ok)
        self.assertIn("Cannot re-issue", msg)

    def test_reissue_requires_same_org(self):
        other_org = Organization.objects.create(name="Other Co", slug="other-co")
        outsider = User.objects.create_user(
            email="other@test.com", password="Passw0rd!123",
            full_name="Other", role=Role.ADMIN, organization=other_org,
        )
        ok, _ = reissue_qr_pass(self.visit, outsider)
        self.assertFalse(ok)

    def test_reissue_rotates_token_signature_and_resets_usage(self):
        qr = self.visit.qr_pass
        qr.is_used = True
        qr.save()
        old_token = str(qr.token)
        old_sig = qr.signature

        ok, msg = reissue_qr_pass(self.visit, self.admin)
        self.assertTrue(ok, msg)

        qr.refresh_from_db()
        self.assertNotEqual(str(qr.token), old_token)
        self.assertNotEqual(qr.signature, old_sig)
        self.assertFalse(qr.is_used)
        ok, vmsg, _ = QRPass.verify(str(qr.token), qr.signature)
        self.assertTrue(ok, vmsg)


class ArchiveOldVisitsTests(SecureGateTestCase):
    """The archiving management command via ``archive_old_visits``."""

    def test_archives_old_checked_out_visits_only(self):
        old = self.register_visit()
        old.status = VisitStatus.CHECKED_OUT
        old.checked_out_at = timezone.now() - timezone.timedelta(days=45)
        old.save()

        recent = self.register_visit()
        recent.status = VisitStatus.CHECKED_OUT
        recent.checked_out_at = timezone.now() - timezone.timedelta(days=5)
        recent.save()

        pending = self.register_visit()  # stays untouched

        out = io.StringIO()
        call_command("archive_old_visits", stdout=out, days=30)

        old.refresh_from_db()
        recent.refresh_from_db()
        pending.refresh_from_db()
        self.assertEqual(old.status, VisitStatus.ARCHIVED)
        self.assertEqual(recent.status, VisitStatus.CHECKED_OUT)
        self.assertEqual(pending.status, VisitStatus.PENDING)
        self.assertIn("Archived 1", out.getvalue())

    def test_organization_scope(self):
        other = Organization.objects.create(name="Other Archive Co", slug="other-archive-co")
        other_visit = Visit.objects.create(
            visitor=self.visitor, organization=other, host=self.admin,
            purpose="Other", status=VisitStatus.CHECKED_OUT,
            checked_out_at=timezone.now() - timezone.timedelta(days=60),
        )
        mine = self.register_visit()
        mine.status = VisitStatus.CHECKED_OUT
        mine.checked_out_at = timezone.now() - timezone.timedelta(days=60)
        mine.save()

        call_command("archive_old_visits", organization=self.org.pk, days=30)
        other_visit.refresh_from_db()
        mine.refresh_from_db()
        self.assertEqual(other_visit.status, VisitStatus.CHECKED_OUT)
        self.assertEqual(mine.status, VisitStatus.ARCHIVED)



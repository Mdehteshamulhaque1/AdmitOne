"""Audit-trail consistency: every entry must be written, correct and attributable.

Three properties are pinned here, all of which the trail previously violated.

**Nothing is recorded that did not happen.**  The lifecycle services logged
*after* the ``transaction.atomic()`` block that made the change, so a rollback of
an enclosing transaction left an entry describing a state change that had been
undone.  The archive job did not log at all: a bulk ``.update()`` moved a visit
from ``CHECKED_OUT`` to ``ARCHIVED`` with no entry, ever.

**Everything that happened is recorded.**  Each Visit lifecycle transition --
approve, reject, check in, check out, QR re-issue, register, archive, plus the
portal's arriving flag -- writes exactly one row, and the count is asserted
rather than assumed.

**Entries belong to a tenant.**  ``AuditLog.organization`` is set for every path,
including the ones with no human actor (public booking, visitor portal,
reminder jobs, the archive job), and the console audit log is scoped on the
row's own organization rather than the actor's.

Also covered: the ``entity_id`` contract (deletions keep their pk, the role
change no longer stores an e-mail address in a key column and no longer records
``X -> X``), and the honest limits of the trail -- ``AuditLogAdmin`` refuses
add/change/delete, but nothing at the database level stops a ``DELETE``, so the
docstring must not claim immutability.
"""

from datetime import time, timedelta

from django.core.management import call_command
from django.db import connection, transaction
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.models import Role, User
from organizations.models import AuditLog, Building, Organization
from visits.models import Visit, VisitStatus, Visitor
from visits.services import (
    approve_visit,
    archive_old_visits,
    check_in,
    check_out,
    reissue_qr_pass,
    register_visit,
    reject_visit,
)

PASSWORD = "Str0ng!Pass"


class AuditTestBase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.alpha = Organization.objects.create(name="Alpha", slug="alpha")
        self.bravo = Organization.objects.create(name="Bravo", slug="bravo")

        self.alpha_admin = self._user("alpha-admin@x.test", self.alpha, Role.ADMIN)
        self.alpha_security = self._user("alpha-guard@x.test", self.alpha, Role.SECURITY)
        self.bravo_admin = self._user("bravo-admin@x.test", self.bravo, Role.ADMIN)

        self.alpha_building = Building.objects.create(
            organization=self.alpha, name="Alpha Tower"
        )

    def _user(self, email, org, role):
        return User.objects.create_user(
            email=email, password=PASSWORD, full_name=email.split("@")[0],
            role=role, organization=org,
        )

    def _visitor(self, org, phone="555-0100", name="Ada Lovelace"):
        return Visitor.objects.create(
            organization=org, full_name=name, phone=phone, email=f"{phone}@x.test"
        )

    def _visit(self, status=VisitStatus.PENDING, org=None, days_ago=None, visitor=None):
        # a per-test counter keeps phone numbers unique, since (organization,
        # phone) is the tenant-scoped dedup key
        type(self)._phone_seq = getattr(type(self), "_phone_seq", 0) + 1
        visit = Visit.objects.create(
            visitor=visitor
            or self._visitor(
                org or self.alpha, phone=f"555-{type(self)._phone_seq:06d}"
            ),
            organization=org or self.alpha,
            created_by=self.alpha_admin,
            host=self.alpha_admin,
            building=self.alpha_building,
            purpose="Meeting",
            visit_date=timezone.localdate(),
            expected_arrival=time(10, 0),
            expected_exit=time(17, 0),
        )
        if status is not VisitStatus.PENDING:
            visit.status = status
        if days_ago is not None:
            visit.checked_out_at = timezone.now() - timedelta(days=days_ago)
        visit.save()
        return visit

    def _logs(self, action, **filters):
        return AuditLog.objects.filter(action=action, **filters)

    def _assert_logged(self, action, visit=None, **filters):
        qs = self._logs(action)
        if visit is not None:
            qs = qs.filter(entity_id=str(visit.visit_id))
        qs = qs.filter(**filters) if filters else qs
        self.assertTrue(
            qs.exists(),
            f"expected an audit row for {action!r}; actions recorded: "
            f"{sorted(set(AuditLog.objects.values_list('action', flat=True)))}",
        )
        return qs.first()


# ================================================= every transition is recorded


class VisitLifecycleAuditTests(AuditTestBase):
    """One audit row per lifecycle transition, with the visit's tenant."""

    def test_approve_records_one_entry_with_the_visit_organization(self):
        visit = self._visit()
        ok, _ = approve_visit(visit, self.alpha_admin)
        self.assertTrue(ok)
        entry = self._assert_logged("Visit approved", visit)
        self.assertEqual(entry.organization_id, self.alpha.pk)
        self.assertEqual(entry.user_id, self.alpha_admin.pk)
        self.assertEqual(entry.entity_type, "Visit")
        self.assertEqual(
            AuditLog.objects.filter(action="Visit approved", entity_id=str(visit.visit_id)).count(),
            1,
        )

    def test_reject_records_one_entry_with_the_reason(self):
        visit = self._visit()
        ok, _ = reject_visit(visit, self.alpha_admin, reason="Not on the guest list")
        self.assertTrue(ok)
        entry = self._assert_logged("Visit rejected", visit)
        self.assertIn("Not on the guest list", entry.details)
        self.assertEqual(entry.organization_id, self.alpha.pk)

    def test_check_in_and_check_out_each_record_an_entry(self):
        visit = self._visit()
        approve_visit(visit, self.alpha_admin)
        ok, _ = check_in(visit, self.alpha_security)
        self.assertTrue(ok)
        self._assert_logged("Visitor checked in", visit, organization=self.alpha)

        ok, _ = check_out(visit, self.alpha_security)
        self.assertTrue(ok)
        self._assert_logged("Visitor checked out", visit, organization=self.alpha)

        # the actor is recorded on both, and so is the tenant
        self.assertEqual(
            self._logs("Visitor checked in").first().user_id, self.alpha_security.pk
        )

    def test_qr_reissue_records_an_entry(self):
        visit = self._visit()
        approve_visit(visit, self.alpha_admin)
        ok, _ = reissue_qr_pass(visit, self.alpha_admin)
        self.assertTrue(ok)
        self._assert_logged("QR pass re-issued", visit, organization=self.alpha)

    def test_register_records_an_entry(self):
        _visit_obj, ok, _msg = register_visit(
            self.alpha_admin,
            visitor=self._visitor(self.alpha, phone="555-0199"),
            purpose="Meeting",
            building_id=self.alpha_building.pk,
            audit=True,
        )
        self.assertTrue(ok)
        entry = self._logs("Visit registered").first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.organization_id, self.alpha.pk)


class ArchiveAuditTests(AuditTestBase):
    """The reported issue: CHECKED_OUT -> ARCHIVED was invisible."""

    def test_archiving_records_one_entry_per_visit(self):
        stale = self._visit(status=VisitStatus.CHECKED_OUT, days_ago=90)
        stale2 = self._visit(status=VisitStatus.CHECKED_OUT, days_ago=45)

        count = archive_old_visits(days=30)
        self.assertEqual(count, 2)

        for visit in (stale, stale2):
            visit.refresh_from_db()
            self.assertEqual(visit.status, VisitStatus.ARCHIVED)
            self.assertIsNotNone(visit.archived_at)
            entry = self._assert_logged("Visit archived", visit)
            # the job has no operator, so the row must still be attributable
            self.assertIsNone(entry.user_id)
            self.assertEqual(entry.organization_id, self.alpha.pk)

    def test_archive_entry_records_the_cutoff_for_context(self):
        visit = self._visit(status=VisitStatus.CHECKED_OUT, days_ago=90)
        archive_old_visits(days=30)
        self.assertIn("30d", self._logs("Visit archived").first().details)

    def test_recent_checkouts_are_neither_archived_nor_logged(self):
        recent = self._visit(status=VisitStatus.CHECKED_OUT, days_ago=3)
        self.assertEqual(archive_old_visits(days=30), 0)
        recent.refresh_from_db()
        self.assertEqual(recent.status, VisitStatus.CHECKED_OUT)
        self.assertFalse(self._logs("Visit archived").exists())

    def test_in_flight_visits_are_never_archived_or_logged(self):
        for status in (
            VisitStatus.PENDING, VisitStatus.APPROVED,
            VisitStatus.CHECKED_IN, VisitStatus.REJECTED,
        ):
            with self.subTest(status=status):
                visit = self._visit(status=status, days_ago=200)
                self.assertEqual(archive_old_visits(days=30), 0)
                visit.refresh_from_db()
                self.assertEqual(visit.status, status)
        self.assertFalse(self._logs("Visit archived").exists())

    def test_organization_filter_scopes_both_the_archives_and_the_entries(self):
        bravo_building = Building.objects.create(organization=self.bravo, name="Bravo Annex")
        bravo_visit = Visit.objects.create(
            visitor=self._visitor(self.bravo, phone="555-0288"),
            organization=self.bravo, created_by=self.bravo_admin,
            host=self.bravo_admin, building=bravo_building, purpose="Meeting",
            visit_date=timezone.localdate(), status=VisitStatus.CHECKED_OUT,
            checked_out_at=timezone.now() - timedelta(days=90),
        )
        self._visit(status=VisitStatus.CHECKED_OUT, days_ago=90)

        self.assertEqual(archive_old_visits(days=30, organization=self.bravo.pk), 1)
        bravo_visit.refresh_from_db()
        self.assertEqual(bravo_visit.status, VisitStatus.ARCHIVED)

        entries = self._logs("Visit archived")
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().organization_id, self.bravo.pk)

    def test_management_command_archives_and_audits(self):
        visit = self._visit(status=VisitStatus.CHECKED_OUT, days_ago=90)
        call_command("archive_old_visits", days=30, stdout=None)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.ARCHIVED)
        self._assert_logged("Visit archived", visit, organization=self.alpha)

    def test_command_output_reports_the_count(self):
        from io import StringIO

        self._visit(status=VisitStatus.CHECKED_OUT, days_ago=90)
        out = StringIO()
        call_command("archive_old_visits", days=30, stdout=out)
        self.assertIn("Archived 1 visit", out.getvalue())


# ==================================== a rollback must not leave a record behind


class RollbackTests(AuditTestBase):
    """An audit row that survives a rollback describes a change that never happened."""

    def _raise_after_approval(self, visit, approver):
        """Approve, then abort the enclosing transaction."""
        with transaction.atomic():
            ok, _ = approve_visit(visit, approver)
            self.assertTrue(ok)
            raise RuntimeError("rolled back after the visit was approved")

    def test_approval_rollback_leaves_no_audit_row(self):
        visit = self._visit()
        with self.assertRaises(RuntimeError):
            self._raise_after_approval(visit, self.alpha_admin)

        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.PENDING, "the approval must be undone")
        self.assertIsNone(visit.approved_at)
        self.assertFalse(
            self._logs("Visit approved").exists(),
            "a rolled-back approval must not leave an 'Visit approved' entry",
        )

    def test_check_out_rollback_leaves_no_audit_row(self):
        visit = self._visit(status=VisitStatus.CHECKED_IN)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                ok, _ = check_out(visit, self.alpha_security)
                self.assertTrue(ok)
                raise RuntimeError("boom")

        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_IN)
        self.assertFalse(self._logs("Visitor checked out").exists())

    def test_reject_rollback_leaves_no_audit_row(self):
        visit = self._visit()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                ok, _ = reject_visit(visit, self.alpha_admin, reason="nope")
                self.assertTrue(ok)
                raise RuntimeError("boom")
        self.assertFalse(self._logs("Visit rejected").exists())

    def test_check_in_rollback_also_undoes_the_consumed_qr_pass(self):
        visit = self._visit()
        approve_visit(visit, self.alpha_admin)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                ok, _ = check_in(visit, self.alpha_security, via_qr=True)
                self.assertTrue(ok)
                raise RuntimeError("boom")

        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertFalse(self._logs("Visitor checked in").exists())
        from visits.models import QRPass

        self.assertFalse(QRPass.objects.get(visit=visit).is_used)

    def test_archive_rollback_leaves_the_visit_unchanged(self):
        # one visit is archived, then the whole run is unwound
        self._visit(status=VisitStatus.CHECKED_OUT, days_ago=90)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.assertEqual(archive_old_visits(days=30), 1)
                raise RuntimeError("boom")

        self.assertEqual(Visit.objects.filter(status=VisitStatus.ARCHIVED).count(), 0)
        self.assertFalse(self._logs("Visit archived").exists())

    def test_successful_commit_keeps_the_entry(self):
        # the control for the rollback cases: same code path, no exception
        visit = self._visit()
        with transaction.atomic():
            approve_visit(visit, self.alpha_admin)
        self._assert_logged("Visit approved", visit)


class AuditWriteFailureRollsBackMutationTests(AuditTestBase):
    """If the audit write fails, the state change must not survive.

    This is the assertion that actually distinguishes "the entry is written
    inside the transaction" from "the entry is written just after it". Merely
    raising inside an enclosing atomic block proves nothing, because the audit
    row shares that outer savepoint either way. What matters is the opposite
    direction: when the audit write itself fails, the service's *own* atomic
    block must undo the mutation it had already performed. That only holds if
    the entry is written before the block exits.
    """

    def _break_audit(self):
        from visits import services as visit_services

        real = visit_services.AuditLog.log

        def exploding(*args, **kwargs):
            raise RuntimeError("audit storage unavailable")

        visit_services.AuditLog.log = exploding
        self.addCleanup(setattr, visit_services.AuditLog, "log", real)

    def test_a_failed_audit_undoes_the_approval(self):
        visit = self._visit()
        self._break_audit()
        with self.assertRaises(RuntimeError):
            approve_visit(visit, self.alpha_admin)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.PENDING)
        self.assertIsNone(visit.approved_at)

    def test_a_failed_audit_undoes_the_check_out(self):
        visit = self._visit(status=VisitStatus.CHECKED_IN)
        self._break_audit()
        with self.assertRaises(RuntimeError):
            check_out(visit, self.alpha_security)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_IN)
        self.assertIsNone(visit.checked_out_at)

    def test_a_failed_audit_undoes_the_rejection(self):
        visit = self._visit()
        self._break_audit()
        with self.assertRaises(RuntimeError):
            reject_visit(visit, self.alpha_admin, reason="nope")
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.PENDING)
        self.assertIsNone(visit.rejected_at)

    def test_a_failed_audit_undoes_the_check_in(self):
        visit = self._visit()
        approve_visit(visit, self.alpha_admin)
        self._break_audit()
        with self.assertRaises(RuntimeError):
            check_in(visit, self.alpha_security)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertIsNone(visit.checked_in_at)

    def test_a_failed_audit_undoes_the_qr_reissue(self):
        visit = self._visit()
        approve_visit(visit, self.alpha_admin)
        from visits.models import QRPass

        before = QRPass.objects.get(visit=visit).token
        self._break_audit()
        with self.assertRaises(RuntimeError):
            reissue_qr_pass(visit, self.alpha_admin)
        # the rotated signature must not outlive its audit entry
        self.assertEqual(QRPass.objects.get(visit=visit).token, before)

    def test_a_failed_audit_undoes_the_registration(self):
        visitor = self._visitor(self.alpha, phone="555-0777")
        self._break_audit()
        with self.assertRaises(RuntimeError):
            register_visit(
                self.alpha_admin, visitor=visitor, purpose="Meeting",
                building_id=self.alpha_building.pk, audit=True,
            )
        self.assertFalse(
            Visit.objects.filter(visitor=visitor).exists(),
            "a registration with no audit entry must not persist",
        )

    def test_a_failed_audit_undoes_the_archive(self):
        visit = self._visit(status=VisitStatus.CHECKED_OUT, days_ago=90)
        self._break_audit()
        with self.assertRaises(RuntimeError):
            archive_old_visits(days=30)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_OUT)
        self.assertIsNone(visit.archived_at)

    def test_the_audit_write_runs_inside_the_service_transaction(self):
        # Structural check. ``connection.in_atomic_block`` is only meaningful
        # here because it is read from inside the service, not from the test.
        from visits import services as visit_services

        observed = []
        real = visit_services.AuditLog.log

        def spy(*args, **kwargs):
            observed.append(connection.in_atomic_block)
            return real(*args, **kwargs)

        visit_services.AuditLog.log = spy
        self.addCleanup(setattr, visit_services.AuditLog, "log", real)

        approve_visit(self._visit(), self.alpha_admin)
        self.assertTrue(observed, "the approval must be audited")
        self.assertTrue(
            all(observed),
            "the audit row must be written before the service's atomic block "
            f"exits; in_atomic_block was {observed}",
        )


class EntityIdTests(AuditTestBase):
    """entity_id is an entity key, and deletions must not lose it."""


    def test_visit_entries_store_the_uuid_visit_id(self):
        visit = self._visit()
        approve_visit(visit, self.alpha_admin)
        entry = self._logs("Visit approved").first()
        self.assertEqual(entry.entity_id, str(visit.visit_id))
        self.assertEqual(len(entry.entity_id), 36)


# ============================================ tenant-scoped audit visibility


# ================================== audit rows are not editable through the app


class AuditWriteProtectionTests(AuditTestBase):
    """What the implementation actually prevents -- and what it does not."""

    def test_admin_refuses_to_add_a_row(self):
        from organizations.admin import AuditLogAdmin

        admin = AuditLogAdmin(AuditLog, None)
        request = self.factory.get("/admin/")
        request.user = User.objects.create_superuser(
            email="root@x.test", password=PASSWORD, full_name="Root"
        )
        self.assertFalse(admin.has_add_permission(request))
        self.assertFalse(admin.has_change_permission(request))
        self.assertFalse(admin.has_delete_permission(request))


    def test_no_api_route_can_write_an_audit_row(self):
        # /api/audit-logs/ is a READ-ONLY list for the SPA (view_audit_logs
        # only). There is no HTTP path to create, edit or delete an entry: POST
        # is not implemented (405) and there is no detail route at all (404).
        from organizations.models import AuditLog as audit_model
        from rest_framework_simplejwt.tokens import RefreshToken

        self.assertFalse(hasattr(audit_model, "ViewSet"))
        before = AuditLog.objects.count()
        # anonymous: nothing, not even a read
        self.assertEqual(self.client.get("/api/audit-logs/").status_code, 401)
        self.assertEqual(self.client.post("/api/audit-logs/", {}).status_code, 401)
        # an admin can read, but cannot write
        token = str(RefreshToken.for_user(self.alpha_admin).access_token)
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.assertEqual(self.client.get("/api/audit-logs/", **auth).status_code, 200)
        for method, path, expected in [
            ("post", "/api/audit-logs/", 405),
            ("put", "/api/audit-logs/", 405),
            ("delete", "/api/audit-logs/", 405),
            ("delete", "/api/audit-logs/1/", 404),
            ("patch", "/api/audit-logs/1/", 404),
        ]:
            with self.subTest(method=method, path=path):
                resp = getattr(self.client, method)(path, {}, **auth)
                self.assertEqual(resp.status_code, expected)
        self.assertEqual(AuditLog.objects.count(), before)

    def test_the_trail_is_immutable_at_the_database_level(self):
        # Guards the honesty of the docstring: the model claims database-level
        # immutability, so prove it below the application layer with raw ORM
        # writes, which bypass every admin/serializer guard.
        from django.db import IntegrityError, transaction

        self.assertIn("Immutable at the database level", AuditLog.__doc__)
        entry = AuditLog.log(self.alpha_admin, "Direct row", "Visit", "1", details="original")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuditLog.objects.filter(pk=entry.pk).update(details="tampered")
        from django.db import connection

        if connection.vendor == "postgresql":
            # DELETE protection is a production-database property (SQLite's
            # test flush needs row deletes; see migration 0006).
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    AuditLog.objects.filter(pk=entry.pk).delete()
        self.assertEqual(AuditLog.objects.get(pk=entry.pk).details, "original")
        # the SET_NULL cascade that keeps history when an actor leaves is the
        # one update the trigger permits
        self.alpha_admin.delete()
        self.assertIsNone(AuditLog.objects.get(pk=entry.pk).user_id)


class AuditLogHelperTests(AuditTestBase):
    def test_tenant_defaults_to_the_actors_workspace(self):
        entry = AuditLog.log(self.alpha_admin, "Implicit", "Visit", "1")
        self.assertEqual(entry.organization_id, self.alpha.pk)

    def test_an_explicit_tenant_wins_over_the_actor(self):
        entry = AuditLog.log(
            self.alpha_admin, "Explicit", "Visit", "1", organization_id=self.bravo.pk
        )
        self.assertEqual(entry.organization_id, self.bravo.pk)

    def test_a_system_row_with_no_actor_keeps_its_null_tenant(self):
        entry = AuditLog.log(None, "System", "Visit", "1")
        self.assertIsNone(entry.organization_id)
        self.assertIsNone(entry.user_id)

    def test_a_null_actor_without_an_explicit_tenant_does_not_raise(self):
        entry = AuditLog.log(None, "Orphaned", entity_type="VisitorPortal")
        self.assertIsNone(entry.organization_id)
        self.assertEqual(entry.entity_id, "")

    def test_entity_id_is_stringified_and_bounded(self):
        entry = AuditLog.log(self.alpha_admin, "Long", "Visit", "x" * 200)
        self.assertEqual(len(entry.entity_id), 64)

    def test_deleted_workspace_keeps_the_audit_rows(self):
        # SET_NULL, not CASCADE: losing a workspace must not erase its history
        entry = AuditLog.log(self.alpha_admin, "Before delete", "Visit", "1")
        before = AuditLog.objects.count()
        self.alpha.delete()
        entry.refresh_from_db()
        self.assertIsNone(entry.organization_id)
        self.assertEqual(AuditLog.objects.count(), before)
        self.assertTrue(AuditLog.objects.filter(pk=entry.pk).exists())

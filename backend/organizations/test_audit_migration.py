"""The `0004_auditlog_tenant_key` backfill, exercised against a real 0003 schema.

The backfill runs once, on production data it cannot see from here, and its
reverse operation is a no-op -- so a wrong attribution is not recoverable by
reverting and reapplying. It therefore gets a dedicated suite that builds a
genuine pre-0004 schema, inserts rows the way the old code wrote them, and
applies the migration for real.

The rule being pinned is deliberately conservative: attribute a row only when
the answer is unambiguous, and leave everything else NULL rather than guess.
Every case below is a row a real deployment could plausibly be holding.

Django 5.x removed ``MigratorTestCase``, so the two-line base that replaced it
lives here: migrate down in ``setUp``, back to the latest leaf in cleanup.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from config.migration_testing import expand_targets


class MigrationTestCase(TransactionTestCase):
    """Run one app's migrations back and forth around each test."""

    migrate_from = []
    migrate_to = []

    def get_executor(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        complete = expand_targets(targets)
        executor.migrate(complete)
        return executor, complete

    def _migrate(self, targets):
        """Pin ``targets`` and return the historical model registry there.

        ``expand_targets`` leaves every app not named in ``targets`` at its
        latest migration, so rewinding ``organizations`` here does not also
        unapply ``accounts`` or ``visits``. Passing the single-element list
        straight to ``MigrationExecutor`` would have done exactly that, which
        on PostgreSQL rebuilds ``visits`` inside one transaction and fails with
        "cannot CREATE INDEX ... because it has pending trigger events".
        """
        executor, complete = self.get_executor(targets)
        return executor.loader.project_state(complete).apps

    def setUp(self):
        super().setUp()
        self.apps_before = self._migrate(self.migrate_from)
        self.addCleanup(self._migrate_to_latest)

    def _migrate_to_latest(self):
        self._migrate([])


class AuditTenantBackfillTests(MigrationTestCase):
    migrate_from = [("organizations", "0003_organization_weekly_working_hours")]
    migrate_to = [("organizations", "0004_auditlog_tenant_key")]

    def _fixture(self, apps):
        """Create workspaces and users.

        These use the **real** models deliberately. Only ``organizations`` is
        rewound, and ``0004`` touches nothing but ``AuditLog``; the live
        ``accounts`` schema is still at its latest, so the real ``User`` is the
        only registry that knows about ``User.organization`` -- which is
        exactly the column the backfill reads.
        """
        from accounts.models import User
        from organizations.models import Organization

        alpha = Organization.objects.create(name="Alpha", slug="alpha")
        bravo = Organization.objects.create(name="Bravo", slug="bravo")
        member = User.objects.create_user(
            email="member@x.test", password="x", full_name="Member",
            organization=alpha,
        )
        orphan = User.objects.create_user(
            email="orphan@x.test", password="x", full_name="Orphan",
            organization=None,
        )
        return alpha, bravo, member, orphan

    def _insert_legacy(self, user, action, entity_type, entity_id):
        """Write a row exactly as the pre-0004 code did: no organization column.

        Placeholders are ``%s`` rather than ``?``. ``?`` is SQLite's own syntax
        and works only there; Django's SQLite backend rewrites ``%s`` into ``?``
        on the way out, so ``%s`` is the one form that runs on both backends.
        """
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations_auditlog "
                "(action, entity_type, entity_id, details, user_id, created_at) "
                "VALUES (%s, %s, %s, '', %s, CURRENT_TIMESTAMP)",
                [action, entity_type, entity_id, user.id],
            )

    def _insert_system_legacy(self, action, entity_type, entity_id):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO organizations_auditlog "
                "(action, entity_type, entity_id, details, user_id, created_at) "
                "VALUES (%s, %s, %s, '', NULL, CURRENT_TIMESTAMP)",
                [action, entity_type, entity_id],
            )

    def _tenant_of(self, apps, action):
        return apps.get_model("organizations", "AuditLog").objects.filter(
            action=action
        ).values_list("organization_id", flat=True)[0]

    # ------------------------------------------------------------------
    def test_backfill_prefers_the_rows_own_organization_entity(self):
        apps = self.apps_before
        alpha, bravo, member, _orphan = self._fixture(apps)

        # member currently works in alpha, but this row is about bravo
        self._insert_legacy(member, "Workspace created", "Organization", bravo.pk)
        self._insert_legacy(member, "Building created", "Building", "7")

        apps = self._migrate(self.migrate_to)
        self.assertEqual(self._tenant_of(apps, "Workspace created"), bravo.pk)
        self.assertEqual(self._tenant_of(apps, "Building created"), alpha.pk)

    def test_backfill_does_not_trust_a_stale_organization_id(self):
        apps = self.apps_before
        alpha, _bravo, member, _orphan = self._fixture(apps)

        # an Organization that has since been deleted
        self._insert_legacy(member, "Organization updated", "Organization", "99999")
        # and an entity_id that was never an id at all
        self._insert_legacy(member, "Employee created", "Employee", "EMP-0042")

        apps = self._migrate(self.migrate_to)
        # both fall back to the actor rather than producing a dangling key
        self.assertEqual(self._tenant_of(apps, "Organization updated"), alpha.pk)
        self.assertEqual(self._tenant_of(apps, "Employee created"), alpha.pk)

    def test_backfill_leaves_undeducible_rows_null(self):
        apps = self.apps_before
        _alpha, _bravo, _member, orphan = self._fixture(apps)

        self._insert_legacy(orphan, "Building updated", "Building", "9")
        self._insert_system_legacy("Pre-booking submitted", "Visit", "uuid-1")
        self._insert_system_legacy("Reminder sent", "Visit", "uuid-2")

        apps = self._migrate(self.migrate_to)
        AuditLog = apps.get_model("organizations", "AuditLog")
        # an actor with no workspace tells us nothing ...
        self.assertIsNone(self._tenant_of(apps, "Building updated"))
        # ... nor does a row with no actor at all
        self.assertIsNone(self._tenant_of(apps, "Pre-booking submitted"))
        self.assertIsNone(self._tenant_of(apps, "Reminder sent"))
        self.assertEqual(AuditLog.objects.filter(organization__isnull=True).count(), 3)

    def test_backfill_uses_the_actor_for_ordinary_entity_types(self):
        apps = self.apps_before
        alpha, _bravo, member, _orphan = self._fixture(apps)

        # these entity_ids are the same integers as the org pks; only
        # entity_type may decide, so both must follow the actor
        self._insert_legacy(member, "Building deleted", "Building", "1")
        self._insert_legacy(member, "Visit registered", "Visit", "1")

        apps = self._migrate(self.migrate_to)
        self.assertEqual(self._tenant_of(apps, "Building deleted"), alpha.pk)
        self.assertEqual(self._tenant_of(apps, "Visit registered"), alpha.pk)

    def test_backfill_preserves_every_row_and_its_values(self):
        apps = self.apps_before
        _alpha, _bravo, member, orphan = self._fixture(apps)
        expected = 0
        for i in range(5):
            self._insert_legacy(member, f"Action {i}", "Building", str(i))
            expected += 1
        self._insert_legacy(orphan, "Orphan action", "Building", "9")
        self._insert_system_legacy("System action", "Visit", "uuid-9")
        expected += 2

        apps = self._migrate(self.migrate_to)
        AuditLog = apps.get_model("organizations", "AuditLog")
        self.assertEqual(AuditLog.objects.count(), expected)
        # values that were already stored survive untouched
        row = AuditLog.objects.get(action="Action 3")
        self.assertEqual(row.entity_id, "3")
        self.assertEqual(row.user_id, member.pk)

    def test_entity_id_column_is_widened_to_hold_the_longest_key(self):
        apps = self._migrate(self.migrate_to)
        field = apps.get_model("organizations", "AuditLog")._meta.get_field("entity_id")
        self.assertEqual(field.max_length, 64)

        # the longest key the application actually stores is
        # Employee.employee_id at 50 characters
        apps = self.apps_before
        _alpha, _bravo, member, _orphan = self._fixture(apps)
        long_key = "E" + "9" * 49
        self._insert_legacy(member, "Employee updated", "Employee", long_key)
        # ... and a UUID Visit.visit_id is 36
        uuid_key = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self._insert_legacy(member, "Visit approved", "Visit", uuid_key)

        apps = self._migrate(self.migrate_to)
        AuditLog = apps.get_model("organizations", "AuditLog")
        self.assertEqual(
            AuditLog.objects.get(action="Employee updated").entity_id, long_key
        )
        self.assertEqual(
            AuditLog.objects.get(action="Visit approved").entity_id, uuid_key
        )

    def test_the_organization_column_is_nullable_so_system_rows_survive(self):
        apps = self.apps_before
        self._fixture(apps)
        self._insert_system_legacy("Portal arrival", "Visit", "uuid-3")

        apps = self._migrate(self.migrate_to)
        field = apps.get_model("organizations", "AuditLog")._meta.get_field(
            "organization"
        )
        self.assertTrue(field.null, "rows with no actor have no derivable tenant")
        row = apps.get_model("organizations", "AuditLog").objects.get(
            action="Portal arrival"
        )
        self.assertIsNone(row.user_id)
        self.assertIsNone(row.organization_id)

    def test_deleting_a_workspace_keeps_its_audit_history(self):
        # SET_NULL, not CASCADE: the compliance trail must outlive the tenant
        from accounts.models import User
        from organizations.models import Organization

        Organization.objects.create(name="Alpha", slug="alpha")
        Organization.objects.create(name="Bravo", slug="bravo")
        member = User.objects.create_user(
            email="m@x.test", password="x", full_name="M",
            organization=Organization.objects.get(slug="alpha"),
        )
        self._insert_legacy(member, "Building created", "Building", "7")

        apps = self._migrate(self.migrate_to)
        AuditLog = apps.get_model("organizations", "AuditLog")
        entry = AuditLog.objects.get(action="Building created")
        self.assertEqual(entry.organization_id, Organization.objects.get(slug="alpha").pk)

        Organization.objects.filter(slug="alpha").delete()
        entry = AuditLog.objects.get(pk=entry.pk)
        self.assertIsNotNone(
            AuditLog.objects.filter(pk=entry.pk).exists(),
            "deleting a workspace must not delete its audit rows",
        )
        self.assertIsNone(entry.organization_id, "SET_NULL keeps the row")
        self.assertEqual(entry.entity_id, "7")

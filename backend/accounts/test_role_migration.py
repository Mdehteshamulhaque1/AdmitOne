"""``accounts.0003`` must map the legacy roles without granting anybody more.

The six legacy roles (``0001_initial``) were collapsed into three.  The old
data step mapped ``SUPER_ADMIN``, ``ORG_ADMIN``, ``EMPLOYEE`` and ``AUDITOR``
all to ``ADMIN``, so a fresh database built from the old migration state gave
``manage_users``, ``manage_org``, ``scan_qr`` and ``view_audit_logs`` to every
account -- including the ones that had only ever had the old field default
``EMPLOYEE`` and could register a visitor and nothing else.

These tests pin the corrected mapping and, more importantly, pin the *exact*
privilege delta each legacy role is allowed to change by, so a future edit to
``LEGACY_ROLE_MAP`` that widens someone's rights fails here instead of quietly
shipping.
"""

import importlib

from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from accounts.models import Role, User
from accounts.permissions import permissions_for, user_permissions
from config.migration_testing import expand_targets, leaf_targets

migration_0003 = importlib.import_module("accounts.migrations.0003_alter_user_role")
LEGACY_ROLE_MAP = migration_0003.LEGACY_ROLE_MAP

LEGACY_ROLES = ("SUPER_ADMIN", "ORG_ADMIN", "RECEPTIONIST", "SECURITY", "EMPLOYEE", "AUDITOR")

# Permission sets the pre-0003 ``accounts/permissions.py`` gave each role
# (``view_dashboard`` was the shared base and is in every set below).
LEGACY_PERMISSIONS = {
    "SUPER_ADMIN": {
        "view_dashboard",
        "create_visitor", "approve_visitor", "checkin_visitor", "checkout_visitor",
        "manage_org", "manage_buildings", "manage_departments", "manage_employees",
        "manage_users", "view_reports", "view_audit_logs", "blacklist_visitor",
        "badge_print", "scan_qr", "manage_roles", "view_all",
    },
    "ORG_ADMIN": {
        "view_dashboard",
        "create_visitor", "approve_visitor", "checkin_visitor", "checkout_visitor",
        "manage_buildings", "manage_departments", "manage_employees", "manage_users",
        "view_reports", "view_audit_logs", "blacklist_visitor", "badge_print", "view_all",
    },
    "RECEPTIONIST": {"view_dashboard", "create_visitor", "badge_print", "view_reports", "view_all"},
    "SECURITY": {
        "view_dashboard", "scan_qr", "checkin_visitor", "checkout_visitor",
        "view_reports", "view_all",
    },
    "EMPLOYEE": {"view_dashboard", "create_visitor", "approve_visitor", "view_all"},
    "AUDITOR": {"view_dashboard", "view_reports", "view_audit_logs", "view_all"},
}

# The reviewed delta, both directions.  A gain is a right the legacy role did
# *not* have; it is only acceptable where the migration docstring says why.
REVIEWED_GAINS = {
    # `view_visitor_documents` appears in every row because all three current
    # roles hold it; it names an existing capability rather than adding one.
    # `view_visitor_pii` (home address, emergency contact) was split out of
    # the general visitor view for ADMIN and RECEPTIONIST only; SECURITY
    # deliberately does not hold it.
    # `manage_student_passes` (2026-11, 6-month passes for admitted students)
    # is a new ADMIN-only capability, so both legacy admin roles gain it.
    "SUPER_ADMIN": {"view_visitor_documents", "view_visitor_pii", "manage_student_passes"},
    "ORG_ADMIN": {"manage_org", "scan_qr", "view_visitor_documents", "view_visitor_pii", "manage_student_passes"},
    "EMPLOYEE": {"badge_print", "view_reports", "view_visitor_documents", "view_visitor_pii"},
    "AUDITOR": {"create_visitor", "badge_print", "view_visitor_documents", "view_visitor_pii"},
}
REVIEWED_LOSSES = {
    "SUPER_ADMIN": {"manage_roles", "view_all"},
    "ORG_ADMIN": {"view_all"},
    "EMPLOYEE": {"approve_visitor", "view_all"},
    "AUDITOR": {"view_audit_logs", "view_all"},
}


class _FakeSchemaEditor:
    """``map_legacy_roles`` only needs the db alias off the schema editor."""

    connection = connection


class LegacyRoleMappingTests(TransactionTestCase):
    """Migrate a planted legacy database forward and audit the result."""

    migrate_from = ("accounts", "0002_initial")
    migrate_to = ("accounts", "0003_alter_user_role")

    def _migrate(self, target):
        """Pin ``target`` and return the historical model registry there.

        ``expand_targets`` keeps every app not named in ``target`` at its latest
        migration. Passing the bare single-element ``[target]`` to
        ``MigrationExecutor`` instead unapplied every *other* app too, so this
        test was silently rewriting the entire schema -- which is both slow and,
        on PostgreSQL, fatal: rebuilding an app inside one transaction fails
        with "cannot CREATE INDEX ... because it has pending trigger events".
        """
        complete = expand_targets([target])
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(complete)
        return executor.loader.project_state(complete).apps

    def _migrate_to_latest(self):
        """Restore the whole schema.

        ``leaf_nodes()`` names the tip of every app, which is the only target
        that genuinely means "latest", and it keeps this correct as migrations
        are added -- naming a migration here would pin the restore to whatever
        happened to be newest when the test was written.
        """
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(leaf_targets())

    def setUp(self):
        old_apps = self._migrate(self.migrate_from)
        self.addCleanup(self._migrate_to_latest)
        OldUser = old_apps.get_model("accounts", "User")

        self.snapshot = {}
        for index, role in enumerate(LEGACY_ROLES):
            user = OldUser.objects.create(
                email=f"legacy-{role.lower()}@example.com",
                password=f"hashed-secret-{index}",
                full_name=f"Legacy {role}",
                role=role,
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            self.snapshot[role] = user
        # a genuine super administrator, the way the legacy create_superuser built one
        self.superuser = OldUser.objects.create(
            email="legacy-root@example.com",
            password="hashed-secret-root",
            full_name="Legacy Root",
            role="SUPER_ADMIN",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        # a role string nobody recognises: it must not be promoted to anything
        self.orphan = OldUser.objects.create(
            email="legacy-unknown@example.com",
            password="hashed-secret-orphan",
            full_name="Legacy Unknown",
            role="SOME_RETIRED_ROLE",
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
        self.user_count = OldUser.objects.count()

        self._migrate(self.migrate_to)

    # -------------------------------------------------- the mapping itself

    def test_every_legacy_role_lands_on_its_documented_role(self):
        for role, mapped in LEGACY_ROLE_MAP.items():
            with self.subTest(role=role):
                user = User.objects.get(pk=self.snapshot[role].pk)
                self.assertEqual(user.role, mapped)
                self.assertIn(user.role, dict(Role.choices))

    def test_roles_that_survived_the_rename_are_untouched(self):
        for role in ("RECEPTIONIST", "SECURITY"):
            with self.subTest(role=role):
                self.assertEqual(
                    User.objects.get(pk=self.snapshot[role].pk).role, role
                )

    def test_employee_is_not_promoted_to_admin(self):
        # the headline F1 regression: the old field default was EMPLOYEE
        user = User.objects.get(pk=self.snapshot["EMPLOYEE"].pk)
        self.assertNotEqual(user.role, Role.ADMIN)
        self.assertNotIn("manage_users", user_permissions(user))
        self.assertNotIn("view_audit_logs", user_permissions(user))

    def test_auditor_is_not_promoted_to_admin(self):
        user = User.objects.get(pk=self.snapshot["AUDITOR"].pk)
        self.assertNotEqual(user.role, Role.ADMIN)
        self.assertNotIn("manage_users", user_permissions(user))
        self.assertNotIn("scan_qr", user_permissions(user))

    def test_unrecognised_role_is_left_alone(self):
        self.assertEqual(
            User.objects.get(pk=self.orphan.pk).role, "SOME_RETIRED_ROLE"
        )

    # -------------------------------------------------- privilege deltas

    def test_no_legacy_role_gains_more_than_was_reviewed(self):
        for role, gains in REVIEWED_GAINS.items():
            with self.subTest(role=role):
                mapped = LEGACY_ROLE_MAP[role]
                granted = permissions_for(mapped) - LEGACY_PERMISSIONS[role]
                self.assertEqual(
                    granted, gains,
                    f"{role} -> {mapped} grants {sorted(granted)}, "
                    f"which is not the reviewed set",
                )

    def test_no_legacy_role_loses_more_than_was_reviewed(self):
        for role, losses in REVIEWED_LOSSES.items():
            with self.subTest(role=role):
                mapped = LEGACY_ROLE_MAP[role]
                dropped = LEGACY_PERMISSIONS[role] - permissions_for(mapped)
                self.assertEqual(dropped, losses)

    def test_superuser_keeps_the_full_permission_set(self):
        user = User.objects.get(pk=self.superuser.pk)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.role, Role.ADMIN)
        # is_superuser dominates the role column, so nothing was taken away
        self.assertEqual(user_permissions(user), permissions_for(Role.ADMIN))
        self.assertIn("manage_users", user_permissions(user))

    def test_mapped_admin_users_can_still_do_the_admin_job(self):
        # the two mapped-to-ADMIN legacy roles must not lose a capability
        for role in ("SUPER_ADMIN", "ORG_ADMIN"):
            with self.subTest(role=role):
                user = User.objects.get(pk=self.snapshot[role].pk)
                for permission in (
                    "manage_users", "manage_buildings", "manage_departments",
                    "manage_employees", "view_audit_logs", "approve_visitor",
                    "checkin_visitor", "checkout_visitor", "blacklist_visitor",
                ):
                    self.assertIn(permission, user_permissions(user))

    def test_mapped_receptionists_can_still_register_visitors(self):
        for role in ("EMPLOYEE", "AUDITOR"):
            with self.subTest(role=role):
                user = User.objects.get(pk=self.snapshot[role].pk)
                self.assertIn("create_visitor", user_permissions(user))

    # -------------------------------------------------- no data destroyed

    def test_no_user_row_is_lost(self):
        self.assertEqual(User.objects.count(), self.user_count)

    def test_no_user_field_other_than_role_is_touched(self):
        for role, planted in self.snapshot.items():
            with self.subTest(role=role):
                user = User.objects.get(pk=planted.pk)
                self.assertEqual(user.email, planted.email)
                self.assertEqual(user.password, planted.password)
                self.assertEqual(user.full_name, planted.full_name)
                self.assertEqual(user.is_active, planted.is_active)
                self.assertEqual(user.is_staff, planted.is_staff)
                self.assertEqual(user.is_superuser, planted.is_superuser)
                self.assertEqual(user.organization_id, planted.organization_id)
                self.assertEqual(user.failed_login_attempts, 0)
        root = User.objects.get(pk=self.superuser.pk)
        self.assertTrue(root.is_superuser)
        self.assertTrue(root.is_staff)
        self.assertEqual(root.password, "hashed-secret-root")

    # -------------------------------------------------- determinism

    def test_map_is_deterministic_and_disjoint(self):
        targets = set(LEGACY_ROLE_MAP.values())
        self.assertEqual(
            targets & set(LEGACY_ROLE_MAP), set(),
            "a target value that is also a source would make the order matter",
        )
        self.assertTrue(targets <= {choice for choice, _ in Role.choices})
        self.assertEqual(set(LEGACY_ROLE_MAP), {"SUPER_ADMIN", "ORG_ADMIN", "EMPLOYEE", "AUDITOR"})

    def test_reapplying_the_data_step_changes_nothing(self):
        before = dict(
            User.objects.values_list("pk", "role")
        )
        migration_0003.map_legacy_roles(django_apps, _FakeSchemaEditor)
        after = dict(User.objects.values_list("pk", "role"))
        self.assertEqual(before, after)


class CurrentRolePermissionsTests(TestCase):
    """Requirement: the three current roles keep behaving exactly as before.

    One permission has been added to all three sets since this contract was
    written: ``view_visitor_documents``, guarding `visits:document`. It is
    behaviour-preserving — every role that could already open a visitor detail
    page (and so already follow the document link) now holds the name
    explicitly — but it is listed here rather than quietly tolerated, because
    the point of this class is that any change to these sets is deliberate.
    """

    def test_admin_permissions_are_unchanged(self):
        self.assertEqual(
            permissions_for(Role.ADMIN),
            {
                "view_dashboard", "create_visitor", "approve_visitor",
                "checkin_visitor", "checkout_visitor", "manage_org",
                "manage_buildings", "manage_departments", "manage_employees",
                "manage_users", "view_reports", "view_audit_logs",
                "blacklist_visitor", "badge_print", "scan_qr",
                "view_visitor_documents", "view_visitor_pii",
                # Added 2026-11 with 6-month student passes (admins only).
                "manage_student_passes",
            },
        )

    def test_receptionist_permissions_are_unchanged(self):
        self.assertEqual(
            permissions_for(Role.RECEPTIONIST),
            {
                "view_dashboard", "create_visitor", "badge_print",
                "view_reports", "view_visitor_documents", "view_visitor_pii",
            },
        )

    def test_security_permissions_are_unchanged(self):
        self.assertEqual(
            permissions_for(Role.SECURITY),
            {
                "view_dashboard", "scan_qr", "checkin_visitor", "checkout_visitor",
                "blacklist_visitor", "view_reports", "view_visitor_documents",
            },
        )

    def test_every_role_that_can_see_a_visitor_can_see_its_document(self):
        # The property behind adding the permission to all three sets: it does
        # not narrow or widen who can reach a document, it only names the check.
        for role in Role.values:
            with self.subTest(role=role):
                self.assertIn("view_visitor_documents", permissions_for(role))

    def test_dropped_legacy_permissions_stay_dropped(self):
        for role in Role.values:
            with self.subTest(role=role):
                granted = permissions_for(role)
                self.assertNotIn("manage_roles", granted)
                self.assertNotIn("view_all", granted)

    def test_unrecognised_role_gets_no_permissions_at_all(self):
        self.assertEqual(permissions_for("SOME_RETIRED_ROLE"), {"view_dashboard"})

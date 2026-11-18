"""F4: a user with no workspace must not reach another tenant's users.

``User.organization`` is nullable for two ordinary reasons: a self-registered
user has none until it completes onboarding, and ``on_delete=SET_NULL`` leaves
one without after a workspace is deleted.  Both states are *not* a tenant.

The two code paths that treated "no organization" as a filter value were the
problem, because ``filter(organization=None)`` compiles to ``IS NULL`` rather
than matching nothing:

* ``GET /api/hosts/`` handed a null-org caller the e-mail address and phone
  number of *every* unassigned account in the deployment;
* the console "Roles & Users" page listed every unassigned account to a
  null-org role-ADMIN, and its POST branch let that account rewrite any of
  them -- by direct id -- because the object lookup was scoped by the same
  ``None``.

These tests pin the tenant requirement at the authorization layer
(``accounts.permissions``) and at both consuming views, and they pin the six-way
matrix the finding calls for: null-org, same-org and different-org callers
across ADMIN, RECEPTIONIST and SECURITY.  Onboarding itself must keep working
-- a null-org user is the normal state for a brand-new account, and creating
its own workspace is the one thing it is allowed to do.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from accounts.permissions import (
    can_manage_users,
    has_tenant,
    tenant_user_queryset,
)
from organizations.models import Building, Department, Organization

PASSWORD = "Str0ng!Pass"


# ================================================================== /api/hosts/


class OrgScopingTestBase(TestCase):
    """Two tenants plus a set of accounts that have not joined either."""

    def setUp(self):
        self.client = APIClient()

        self.alpha = Organization.objects.create(name="Alpha", slug="alpha")
        self.bravo = Organization.objects.create(name="Bravo", slug="bravo")

        self.alpha_admin = self._user("alpha-admin@x.test", self.alpha, Role.ADMIN)
        self.alpha_receptionist = self._user("alpha-desk@x.test", self.alpha, Role.RECEPTIONIST)
        self.alpha_security = self._user("alpha-guard@x.test", self.alpha, Role.SECURITY)
        self.alpha_inactive = self._user("alpha-gone@x.test", self.alpha, Role.RECEPTIONIST)
        self.alpha_inactive.is_active = False
        self.alpha_inactive.save()

        self.bravo_admin = self._user("bravo-admin@x.test", self.bravo, Role.ADMIN)
        self.bravo_receptionist = self._user("bravo-desk@x.test", self.bravo, Role.RECEPTIONIST)

        # the F4 caller: a role-ADMIN that belongs to no workspace
        self.unassigned_admin = self._user("orphan-admin@x.test", None, Role.ADMIN)
        # a second unassigned account, the victim of the role-change attempt
        self.other_unassigned = self._user("orphan-two@x.test", None, Role.RECEPTIONIST)
        self.unassigned_receptionist = self._user("orphan-desk@x.test", None, Role.RECEPTIONIST)
        self.unassigned_security = self._user("orphan-guard@x.test", None, Role.SECURITY)

        Building.objects.create(organization=self.alpha, name="Alpha Tower")
        Building.objects.create(organization=self.bravo, name="Bravo Annex")
        Department.objects.create(organization=self.alpha, name="Alpha Ops")

    def _user(self, email, org, role):
        return User.objects.create_user(
            email=email, password=PASSWORD, full_name=email.split("@")[0],
            role=role, organization=org,
        )

    def _api_as(self, user, path):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._token(user)}")
        self.addCleanup(self.client.credentials)
        return self.client.get(path)

    def _token(self, user):
        resp = self.client.post(
            "/api/auth/token/", {"email": user.email, "password": PASSWORD}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        return resp.data["access"]


    def _emails(self, payload):
        return {row["email"] for row in payload}


class HostListApiTests(OrgScopingTestBase):
    """The host picker must never expose accounts outside the caller's org."""

    def test_org_less_user_is_shown_no_hosts(self):
        # the F4 regression: this used to return every unassigned account
        resp = self._api_as(self.unassigned_admin, "/api/hosts/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data, [])
        body = resp.content.decode()
        for leaked in (
            self.other_unassigned.email, self.unassigned_receptionist.email,
            self.unassigned_security.email, self.bravo_admin.email,
            self.alpha_admin.email,
        ):
            self.assertNotIn(leaked, body)

    def test_org_less_receptionist_and_security_are_shown_no_hosts(self):
        for user in (self.unassigned_receptionist, self.unassigned_security):
            with self.subTest(role=user.role):
                resp = self._api_as(user, "/api/hosts/")
                self.assertEqual(resp.status_code, 200, resp.content)
                self.assertEqual(resp.data, [])

    def test_host_list_is_scoped_to_own_organization(self):
        resp = self._api_as(self.alpha_admin, "/api/hosts/")
        self.assertEqual(resp.status_code, 200, resp.content)
        emails = self._emails(resp.data)
        self.assertIn(self.alpha_admin.email, emails)
        self.assertIn(self.alpha_receptionist.email, emails)
        self.assertNotIn(self.bravo_admin.email, emails)
        self.assertNotIn(self.bravo_receptionist.email, emails)
        self.assertNotIn(self.other_unassigned.email, emails)

    def test_host_list_excludes_inactive_same_org_users(self):
        resp = self._api_as(self.alpha_admin, "/api/hosts/")
        self.assertNotIn(self.alpha_inactive.email, self._emails(resp.data))

    def test_every_role_in_a_workspace_sees_the_same_scoped_set(self):
        expected = self._emails(self._api_as(self.alpha_admin, "/api/hosts/").data)
        for user in (self.alpha_receptionist, self.alpha_security):
            with self.subTest(role=user.role):
                resp = self._api_as(user, "/api/hosts/")
                self.assertEqual(resp.status_code, 200, resp.content)
                self.assertEqual(self._emails(resp.data), expected)

    def test_two_tenants_never_overlap(self):
        alpha = self._emails(self._api_as(self.alpha_admin, "/api/hosts/").data)
        bravo = self._emails(self._api_as(self.bravo_admin, "/api/hosts/").data)
        self.assertTrue(alpha)
        self.assertTrue(bravo)
        self.assertEqual(alpha & bravo, set())

    def test_orphaned_user_loses_access_after_its_workspace_is_deleted(self):
        # on_delete=SET_NULL is the other way a user ends up with no org
        self.alpha_admin.organization = None
        self.alpha_admin.save()
        resp = self._api_as(self.alpha_admin, "/api/hosts/")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data, [])
        self.assertNotIn(self.other_unassigned.email, resp.content.decode())


# ============================================================== /api/buildings/


class BuildingListApiTests(OrgScopingTestBase):
    def test_org_less_user_is_shown_no_buildings(self):
        # Fails closed: a caller without a workspace is refused outright
        # (IsTenantMember) rather than handed an organization=None filter that
        # could match unassigned rows. The SPA sends such users to onboarding.
        resp = self._api_as(self.unassigned_admin, "/api/buildings/")
        self.assertEqual(resp.status_code, 403, resp.content)
        self.assertNotIn("Alpha Tower", resp.content.decode())

    def test_buildings_are_scoped_to_own_organization(self):
        resp = self._api_as(self.bravo_admin, "/api/buildings/")
        names = {b["name"] for b in resp.data}
        self.assertIn("Bravo Annex", names)
        self.assertNotIn("Alpha Tower", names)


# ================================================= console: roles & users page


# =============================================== onboarding must keep working


# ================================================ the rule itself, unit level


class TenantRequirementUnitTests(OrgScopingTestBase):
    """The rule lives in accounts.permissions, not in the templates."""

    def test_has_tenant_matrix(self):
        self.assertTrue(has_tenant(self.alpha_admin))
        self.assertTrue(has_tenant(self.alpha_receptionist))
        self.assertTrue(has_tenant(self.alpha_security))
        self.assertFalse(has_tenant(self.unassigned_admin))
        self.assertFalse(has_tenant(self.unassigned_receptionist))
        self.assertFalse(has_tenant(self.unassigned_security))
        # an org in another tenant is not "your" tenant, but it is a tenant
        self.assertTrue(has_tenant(self.bravo_admin))

    def test_has_tenant_is_false_for_anonymous(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(has_tenant(AnonymousUser()))
        self.assertFalse(has_tenant(None))

    def test_can_manage_users_requires_a_workspace(self):
        self.assertTrue(can_manage_users(self.alpha_admin))
        self.assertFalse(can_manage_users(self.unassigned_admin))
        self.assertFalse(can_manage_users(self.alpha_receptionist))
        self.assertFalse(can_manage_users(self.alpha_security))
        self.assertFalse(can_manage_users(self.unassigned_receptionist))
        self.assertFalse(can_manage_users(self.unassigned_security))
        # a different tenant's admin manages their own users, never ours
        self.assertTrue(can_manage_users(self.bravo_admin))

    def test_can_manage_users_is_denied_to_a_superuser_with_no_workspace(self):
        # is_superuser grants every permission, so without the tenant
        # requirement this would be True and the console would list every
        # unassigned account
        root = User.objects.create_superuser(
            email="root@x.test", password=PASSWORD, full_name="Root"
        )
        self.assertIsNone(root.organization)
        self.assertFalse(can_manage_users(root))

    def test_tenant_user_queryset_returns_nothing_without_a_workspace(self):
        self.assertEqual(list(tenant_user_queryset(self.unassigned_admin)), [])
        self.assertEqual(list(tenant_user_queryset(self.unassigned_receptionist)), [])
        self.assertEqual(list(tenant_user_queryset(self.unassigned_security)), [])

    def test_tenant_user_queryset_is_scoped_to_the_own_workspace(self):
        emails = {u.email for u in tenant_user_queryset(self.alpha_admin)}
        self.assertIn(self.alpha_receptionist.email, emails)
        self.assertNotIn(self.bravo_receptionist.email, emails)
        self.assertNotIn(self.other_unassigned.email, emails)

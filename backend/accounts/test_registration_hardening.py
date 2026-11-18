"""An anonymous request must never produce an operational administrator.

Finding C-1. Four separate defects composed into it, and each is pinned here so
that fixing one cannot quietly reopen the path through another:

1. ``User.role`` defaulted to ``ADMIN``, so any code path that constructed a
   ``User`` without naming a role minted an administrator.
2. ``POST /api/auth/register/`` is ``AllowAny`` by design (self-serve signup),
   and did not set a role -- so it inherited that default.
3. ``RegisterSerializer`` listed neither ``role`` nor ``organization`` in
   ``Meta.fields``, and DRF drops unlisted fields *silently*, so a caller
   sending ``role=ADMIN`` received ``201`` and could reasonably believe it
   worked.
4. ``ConsoleLoginView`` required an active role but no workspace, so the
   resulting account could hold a session on the operations console.

The invariant, stated once:

    No unauthenticated request may create an operational ADMIN account.

"Operational" is the load-bearing word, and it is why these tests assert on
**permissions and observable effects** rather than on the ``role`` column. An
account whose column reads ``ADMIN`` but whose permission set does not include
``manage_users`` has still satisfied the invariant; a column assertion could not
tell the two apart, and a permission assertion would not catch a future change
that moved authority out of the role column and into the view.

The legitimate path is asserted too, in ``test_onboarding_grants_admin_of_the_new_workspace``
and its neighbours: signup -> ``POST /api/organizations/`` -> ADMIN of a
workspace the caller themselves created. Signup is not the defect; signup that
*hands out authority* is.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from accounts.permissions import has_perm, user_permissions
from organizations.models import AuditLog, Organization
from visits.models import Visitor


class RegistrationSecurityBase(TestCase):
    """Shared helpers. Every test here starts from zero users."""

    def setUp(self):
        self.api = APIClient()

    def register(self, **overrides):
        """POST the public signup endpoint, anonymously. Returns the response."""
        payload = {
            "email": "newcomer@example.com",
            "full_name": "Newcomer",
            "phone": "",
            "password": "Str0ng!Pass",
        }
        payload.update(overrides)
        return self.api.post("/api/auth/register/", payload, format="json")

    def register_and_fetch(self, **overrides):
        """Register, then return the resulting ``User`` from the database."""
        response = self.register(**overrides)
        self.assertEqual(response.status_code, 201, response.content)
        return User.objects.get(email=overrides.get("email", "newcomer@example.com"))

    def bearer(self, user):
        """A client authenticated as ``user`` via a real token exchange."""
        client = APIClient()
        token = client.post(
            "/api/auth/token/",
            {"email": user.email, "password": "Str0ng!Pass"},
            format="json",
        )
        self.assertEqual(token.status_code, 200, token.content)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token.data['access']}")
        return client


class AnonymousSignupCannotObtainAuthority(RegistrationSecurityBase):
    """Requirements 1-3: the account itself must carry no authority."""

    def test_anonymous_registration_does_not_create_an_admin(self):
        user = self.register_and_fetch()
        self.assertNotEqual(user.role, Role.ADMIN)
        self.assertEqual(user.role, Role.RECEPTIONIST)

    def test_the_new_account_holds_no_privileged_permissions(self):
        """Assert the permission set, not the column (see module docstring)."""
        user = self.register_and_fetch()
        granted = user_permissions(user)
        for privileged in (
            "manage_users",
            "manage_org",
            "manage_buildings",
            "manage_departments",
            "manage_employees",
            "approve_visitor",
            "checkin_visitor",
            "checkout_visitor",
            "scan_qr",
            "view_audit_logs",
            "blacklist_visitor",
        ):
            with self.subTest(permission=privileged):
                self.assertNotIn(privileged, granted)
                self.assertFalse(has_perm(user, privileged))

    def test_the_new_account_has_no_workspace(self):
        self.assertIsNone(self.register_and_fetch().organization)

    def test_the_new_account_is_not_staff_or_superuser(self):
        user = self.register_and_fetch()
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_the_model_default_is_not_privileged(self):
        """Guards the field default itself, independent of the serializer.

        The serializer now sets the role explicitly, so this is the layer that
        would still be exploitable if the default regressed.
        """
        user = User(email="defaulted@example.com", full_name="Defaulted")
        self.assertNotEqual(user.role, Role.ADMIN)
        self.assertNotIn("manage_users", user_permissions(user))


class PrivilegedFieldsAreRejectedNotIgnored(RegistrationSecurityBase):
    """Requirement 2-3: mass-assignment gets a 400, never a silent 201."""

    def test_submitting_role_admin_is_rejected(self):
        response = self.register(role="ADMIN")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("role", response.json())
        self.assertFalse(User.objects.filter(email="newcomer@example.com").exists())

    def test_submitting_an_organization_is_rejected(self):
        other = Organization.objects.create(name="Acme", slug="acme")
        response = self.register(organization=other.pk)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(User.objects.filter(email="newcomer@example.com").exists())

    def test_submitting_organization_as_a_slug_is_rejected(self):
        """A slug would be a different spelling of the same mass-assignment."""
        Organization.objects.create(name="Acme", slug="acme")
        response = self.register(organization="acme")
        self.assertEqual(response.status_code, 400, response.content)

    def test_every_privileged_field_is_refused(self):
        for field, value in [
            ("is_superuser", True),
            ("is_staff", True),
            ("is_active", True),
            ("failed_login_attempts", -99),
            ("locked_until", "2099-01-01T00:00:00Z"),
            ("id", 4242),
        ]:
            with self.subTest(field=field):
                response = self.register(**{field: value})
                self.assertEqual(response.status_code, 400, response.content)
                self.assertFalse(User.objects.exists())

    def test_rejection_happens_before_any_row_is_written(self):
        """Not merely a 400 -- zero side effects."""
        response = self.register(role="ADMIN")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)
        self.assertFalse(AuditLog.objects.exists())

    def test_a_plain_signup_still_works(self):
        """The guard must not have broken the legitimate path."""
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(User.objects.count(), 1)


class TheNewAccountReachesNoPrivilegedSurface(RegistrationSecurityBase):
    """Requirement 4: no privileged endpoint answers for it."""

    def setUp(self):
        super().setUp()
        self.user = self.register_and_fetch()

    def test_the_issued_jwt_is_real_but_not_privileged(self):
        """A JWT is issued on purpose: signup needs one to reach onboarding."""
        response = self.bearer(self.user).get("/api/auth/me/")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["user"]["role"], Role.RECEPTIONIST)
        self.assertIsNone(body["organization"])
        for privileged in ("manage_users", "manage_org", "approve_visitor", "view_audit_logs"):
            with self.subTest(permission=privileged):
                self.assertNotIn(privileged, body["permissions"])

    def test_it_cannot_approve_a_visit(self):
        client = self.bearer(self.user)
        response = client.post("/api/visits/1/approve/")
        self.assertIn(response.status_code, (403, 404), response.content)


    def test_it_sees_no_tenant_data(self):
        """Tenantless, so every tenant-scoped queryset is empty, not unfiltered."""
        org = Organization.objects.create(name="Acme", slug="acme")
        Visitor.objects.create(
            organization=org, full_name="Private Person", phone="9990000001"
        )
        client = self.bearer(self.user)
        for url in ("/api/visitors/", "/api/visits/"):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 200, response.content)
                body = response.content.decode()
                self.assertNotIn("Private Person", body)


class LegitimateOnboardingStillWorks(RegistrationSecurityBase):
    """Requirement 6: the intended promotion path is intact."""

    def onboard(self, client, name="Acme"):
        return client.post("/api/organizations/", {"name": name}, format="json")

    def test_signup_then_onboarding_yields_admin_of_the_new_workspace(self):
        user = self.register_and_fetch()
        client = self.bearer(user)
        response = self.onboard(client)
        self.assertEqual(response.status_code, 201, response.content)

        user.refresh_from_db()
        self.assertEqual(user.role, Role.ADMIN)
        self.assertIsNotNone(user.organization)
        self.assertEqual(user.organization.name, "Acme")
        # Authority is scoped to the workspace they just made.
        self.assertIn("manage_users", user_permissions(user))
        self.assertIn("manage_org", user_permissions(user))


    def test_onboarding_creates_the_audit_record(self):
        self.register_and_fetch()
        client = self.bearer(User.objects.get(email="newcomer@example.com"))
        self.onboard(client)
        self.assertTrue(AuditLog.objects.filter(action="org_created").exists())

    def test_onboarding_cannot_be_run_twice_by_one_account(self):
        """A second call must not re-point the account at another tenant."""
        user = self.register_and_fetch()
        client = self.bearer(user)
        first = self.onboard(client, name="Acme")
        self.assertEqual(first.status_code, 201, first.content)
        user.refresh_from_db()
        first_org_id = user.organization_id

        second = self.onboard(client, name="Hijacked Co")
        self.assertEqual(second.status_code, 400, second.content)
        user.refresh_from_db()
        self.assertEqual(user.organization_id, first_org_id)
        self.assertEqual(user.organization.name, "Acme")
        self.assertFalse(Organization.objects.filter(name="Hijacked Co").exists())

    def test_onboarding_never_adopts_an_existing_workspace(self):
        """`name` is the only input; there is no way to name someone else's."""
        victim = Organization.objects.create(name="Acme", slug="acme")
        user = self.register_and_fetch()
        self.onboard(self.bearer(user), name="Acme")
        user.refresh_from_db()
        self.assertNotEqual(user.organization_id, victim.pk)

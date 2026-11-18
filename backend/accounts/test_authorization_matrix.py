"""Authorization is a backend property, and these tests pin it down.

Three things are defended here, and they are deliberately kept separate because
conflating them is the bug this suite exists to prevent:

1. **Backend authorization** -- every mutating endpoint refuses the roles that
   must not reach it. The table below is the executable statement of "who may do
   what"; each row was read out of that view's own guard, so a view that quietly
   drops or widens its check fails here.
2. **UI visibility** -- ``GET /api/auth/me/`` reports the caller's permissions so
   the SPA can hide links it knows will fail. That report is a courtesy.
3. **The boundary between them** -- a wrong, stale or forged permission list can
   change what the *page* shows and nothing more. Asserted directly, because it
   is the property that actually matters: a client cannot grant itself authority
   by lying.

Refusals are detected by **observable effect**, not by status code. A guard that
fires changes nothing; a view that accepts the request either mutates state or
re-renders its form with a 200. Hard-coding each view's redirect target would
break every time a view improves its error path, and would let a view that
redirects *after* mutating pass.
"""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from accounts.permissions import permissions_for
from organizations.models import (
    AuditLog,
    Building,
    Department,
    Employee,
    Organization,
)
from visits.models import (
    QRPass,
    Blacklist,
    BlacklistReason,
    Visit,
    VisitStatus,
    Visitor,
)

PASSWORD = "Str0ng!Pass"
ROLES = (Role.ADMIN, Role.RECEPTIONIST, Role.SECURITY)





class AuthorizationTestBase(TestCase):
    def setUp(self):
        # APIClient rather than django.test.Client: it adds `credentials()` for
        # the JWT-authenticated API, and still supports force_login() for the
        # session-authenticated console, so one client covers both.
        self.client = APIClient()
        self.org = Organization.objects.create(name="Authz Co", slug="authz-co")
        self.dept = Department.objects.create(organization=self.org, name="Ops")
        self.building = Building.objects.create(organization=self.org, name="HQ")
        # A second building/department, because "cannot delete the last
        # building" would otherwise masquerade as an authorization result.
        self.building2 = Building.objects.create(organization=self.org, name="Annex")
        self.dept2 = Department.objects.create(organization=self.org, name="Finance")
        self.users = {
            role: User.objects.create_user(
                email=f"{role.lower()}@authz.test",
                password=PASSWORD,
                full_name=f"{role} User",
                role=role,
                organization=self.org,
            )
            for role in ROLES
        }
        self.employee = Employee.objects.create(
            user=self.users[Role.ADMIN],
            organization=self.org,
            employee_id="EMP-A1",
            department=self.dept,
            designation="Head",
        )
        self.visitor = Visitor.objects.create(
            organization=self.org, full_name="Ravi Kumar", phone="9999999999"
        )
        # A *separate* visitor carrying an active ban, used only by the
        # blacklist rows. Reusing self.visitor would make `approve_visit`
        # refuse ("Visitor is blacklisted") and quietly change the result of
        # every approval assertion in the same table.
        self.banned_visitor = Visitor.objects.create(
            organization=self.org, full_name="Blocked Person", phone="8888888888"
        )
        self.entry = Blacklist.objects.create(
            visitor=self.banned_visitor,
            reason=BlacklistReason.SECURITY_CONCERN,
            added_by=self.users[Role.ADMIN],
        )
        self.visit = Visit.objects.create(
            visitor=self.visitor,
            organization=self.org,
            building=self.building,
            host=self.users[Role.ADMIN],
            created_by=self.users[Role.ADMIN],
            purpose="Interview",
            visit_date=timezone.localdate(),
        )

    def _ban_the_visitor(self):
        """A live blacklist entry for ``self.banned_visitor``."""
        entry, _created = Blacklist.objects.get_or_create(
            visitor=self.banned_visitor,
            defaults={
                "reason": BlacklistReason.SECURITY_CONCERN,
                "added_by": self.users[Role.ADMIN],
            },
        )
        return entry

    # -- authentication -------------------------------------------------
    #
    # The console is session-authenticated, the API is JWT-only. Mixing them up
    # produces a 401 that looks like an authorization failure and isn't, so the
    # two are separate helpers on purpose.


    def as_role_api(self, role):
        """JWT login, for the DRF API."""
        user = self.users[role]
        resp = self.client.post(
            "/api/auth/token/",
            {"email": user.email, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    # -- observable effect ---------------------------------------------

    def _snapshot(self):
        return {
            "buildings": Building.objects.count(),
            "departments": Department.objects.count(),
            "employees": Employee.objects.count(),
            "blacklist_active": Blacklist.objects.filter(is_active=True).count(),
            "visit_status": Visit.objects.get(pk=self.visit.pk).status,
            # Queried, not reached through visit.qr_pass: it is a one-to-one, so
            # the accessor raises when the visit has not been approved yet.
            "qr_used": sorted(
                QRPass.objects.filter(visit=self.visit).values_list("is_used", flat=True)
            ),
            "audit": AuditLog.objects.count(),
        }






# ---------------------------------------------------------------------------
# 2 + 3. The /me capability report, and the fact that it grants nothing
# ---------------------------------------------------------------------------


class MeCapabilityReportTests(AuthorizationTestBase):
    def _me(self, role):
        self.as_role_api(role)
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        return resp.json()

    def test_the_report_matches_the_permission_source_of_truth(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertEqual(
                    sorted(self._me(role)["permissions"]),
                    sorted(permissions_for(role)),
                    "the report must not drift from accounts/permissions.py",
                )

    def test_role_distinctions_are_preserved(self):
        admin = set(self._me(Role.ADMIN)["permissions"])
        reception = set(self._me(Role.RECEPTIONIST)["permissions"])
        security = set(self._me(Role.SECURITY)["permissions"])

        # ADMIN stays a superset of both -- the pre-existing behaviour.
        self.assertTrue(reception <= admin, "RECEPTIONIST must stay inside ADMIN")
        self.assertTrue(security <= admin, "SECURITY must stay inside ADMIN")

        self.assertIn("create_visitor", reception)
        self.assertNotIn("create_visitor", security)
        self.assertIn("approve_visitor", admin)
        self.assertNotIn("approve_visitor", reception)
        self.assertNotIn("approve_visitor", security)
        self.assertIn("scan_qr", security)
        self.assertNotIn("scan_qr", reception)
        for role in ROLES:
            with self.subTest(role=role):
                self.assertIn("view_reports", self._me(role)["permissions"])

    def test_a_superuser_reports_the_admin_set(self):
        root = User.objects.create_superuser(
            email="root@authz.test", password=PASSWORD, full_name="Root"
        )
        resp = self.client.post(
            "/api/auth/token/", {"email": root.email, "password": PASSWORD}, format="json"
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        body = self.client.get("/api/auth/me/").json()
        self.assertEqual(sorted(body["permissions"]), sorted(permissions_for(Role.ADMIN)))

    def test_the_report_never_leaks_another_account(self):
        body = self._me(Role.RECEPTIONIST)
        self.assertEqual(body["user"]["role"], Role.RECEPTIONIST)
        self.assertNotIn("manage_users", body["permissions"])

    def test_the_report_requires_authentication(self):
        resp = self.client.get("/api/auth/me/")
        self.assertEqual(resp.status_code, 401)

    def test_the_report_exposes_no_secret(self):
        body = self._me(Role.ADMIN)
        blob = str(body).lower()
        for secret in ("password", "token", "secret", "hash", "signing"):
            self.assertNotIn(secret, blob, f"/me leaked something like {secret!r}")


class CapabilitiesGrantNothingTests(AuthorizationTestBase):
    """The capability report is a rendering hint. It must not confer access.

    This is the load-bearing test for "the backend is authoritative": whatever
    the client puts in a request -- a permission list, a role, a forged header,
    a body naming a permission -- the server decides from the session alone.
    """

    def setUp(self):
        super().setUp()
        self.assertEqual(self.visit.status, VisitStatus.PENDING)

    def _assert_still_pending(self):
        self.visit.refresh_from_db()
        self.assertEqual(
            self.visit.status, VisitStatus.PENDING,
            "a RECEPTIONIST approved a visit through the API",
        )

    def test_api_client_asserted_permission_list_changes_nothing(self):
        self.as_role_api(Role.RECEPTIONIST)
        resp = self.client.post(
            f"/api/visits/{self.visit.pk}/approve/",
            {"permissions": ["approve_visitor"], "role": "ADMIN"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403, resp.content[:200])
        self._assert_still_pending()

    def test_a_forged_role_header_changes_nothing(self):
        self.as_role_api(Role.RECEPTIONIST)
        resp = self.client.post(
            f"/api/visits/{self.visit.pk}/approve/",
            {},
            format="json",
            HTTP_X_USER_ROLE="ADMIN",
            HTTP_X_ORGANIZATION=str(self.org.pk),
        )
        self.assertEqual(resp.status_code, 403)
        self._assert_still_pending()

    def test_body_payloads_naming_a_permission_are_ignored(self):
        for payload in ({}, {"role": "ADMIN"}, {"perm": "approve_visitor"}, {"pk": 1},
                        {"approve_visitor": True, "manage_users": True}):
            with self.subTest(payload=payload):
                self.as_role_api(Role.RECEPTIONIST)
                resp = self.client.post(
                    f"/api/visits/{self.visit.pk}/approve/", payload, format="json"
                )
                self.assertEqual(resp.status_code, 403)
                self._assert_still_pending()


    def test_an_admin_cannot_approve_in_another_workspace(self):
        # Authorization and tenancy are separate axes; both must hold.
        other = Organization.objects.create(name="Other Co", slug="other-co")
        other_admin = User.objects.create_user(
            email="other@authz.test", password=PASSWORD, full_name="Other",
            role=Role.ADMIN, organization=other,
        )
        resp = self.client.post(
            "/api/auth/token/",
            {"email": other_admin.email, "password": PASSWORD},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        resp = self.client.post(f"/api/visits/{self.visit.pk}/approve/", {}, format="json")
        self.assertIn(resp.status_code, (403, 404))
        self._assert_still_pending()



"""End-to-end smoke test: hits every registered URL endpoint (API + pages + role gates).

Run explicitly with: python manage.py test e2e_smoke
"""

from datetime import date

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()

from accounts.models import Role
from organizations.models import Building, Department, Employee, Organization
from visits.models import Visit, VisitStatus, Visitor

PASSWORD = "Passw0rd!123"


def jwt_header(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}


class EndpointSmokeTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme Corp", slug="acme")
        self.dept = Department.objects.create(organization=self.org, name="Engineering")
        self.building = Building.objects.create(organization=self.org, name="Tower A", floors=5)

        self.admin = self._user("admin@acme.com", Role.ADMIN)
        self.reception = self._user("reception@acme.com", Role.RECEPTIONIST)
        self.security = self._user("security@acme.com", Role.SECURITY)

        Employee.objects.create(
            user=self.admin, organization=self.org, employee_id="E-1",
            department=self.dept, designation="Head",
        )
        self.visitor = Visitor.objects.create(
            full_name="Ravi Kumar", phone="9999999999", company="Acme",
            organization=self.org,
        )
        self.visit = Visit.objects.create(
            visitor=self.visitor, organization=self.org, building=self.building,
            host=self.admin, created_by=self.reception, purpose="Interview",
            visit_date=date.today(),
        )

    def _user(self, email, role):
        u = User.objects.create_user(email=email, password=PASSWORD, full_name=email, role=role)
        u.organization = self.org
        u.save(update_fields=["organization"])
        return u

    # ------------------------------------------------------------- API

    def test_api_health_public(self):
        resp = self.client.get("/api/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_api_requires_auth(self):
        for path in ["/api/visits/", "/api/visitors/", "/api/auth/me/",
                     "/api/hosts/", "/api/buildings/", "/api/dashboard/summary/"]:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 401, path)

    def test_api_auth_register_token_refresh_me(self):
        reg = self.client.post(
            "/api/auth/register/",
            {"email": "new@acme.com", "full_name": "New User", "phone": "8888888888",
             "password": PASSWORD},
            format="json",
        )
        self.assertEqual(reg.status_code, 201, reg.content)
        tokens = reg.json()
        self.assertIn("access", tokens)
        self.assertIn("refresh", tokens)

        tok = self.client.post(
            "/api/auth/token/",
            {"email": "new@acme.com", "password": PASSWORD}, format="json",
        )
        self.assertEqual(tok.status_code, 200, tok.content)
        tok_data = tok.json()

        refresh = self.client.post(
            "/api/auth/token/refresh/", {"refresh": tok_data["refresh"]}, format="json",
        )
        self.assertEqual(refresh.status_code, 200, refresh.content)

        me = self.client.get(
            "/api/auth/me/", **jwt_header(self.admin)
        )
        self.assertEqual(me.status_code, 200, me.content)
        self.assertEqual(me.json()["user"]["email"], "admin@acme.com")

    def test_api_org_create_sets_up_workspace(self):
        reg = self.client.post(
            "/api/auth/register/",
            {"email": "founder@acme.com", "full_name": "Fou Nder", "phone": "7777777777",
             "password": PASSWORD},
            format="json",
        )
        token = reg.json()["access"]
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        resp = self.client.post(
            "/api/organizations/",
            {"name": "Founder Workspace", "building_name": "Office"},
            format="json", **auth,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertIsNotNone(data["organization"]["slug"])
        self.assertTrue(Building.objects.filter(name="Office").exists())

    def test_api_list_endpoints_admin(self):
        h = jwt_header(self.admin)
        list_urls = [
            ("/api/visitors/", 200),
            ("/api/visitors/?q=ravi", 200),
            ("/api/visitors/?page=1", 200),
            ("/api/visits/", 200),
            ("/api/visits/?status=PENDING", 200),
            ("/api/hosts/", 200),
            ("/api/buildings/", 200),
            ("/api/dashboard/summary/", 200),
        ]
        for path, code in list_urls:
            resp = self.client.get(path, **h)
            self.assertEqual(resp.status_code, code, path)

    def test_api_register_visit_and_detail(self):
        h = jwt_header(self.admin)
        resp = self.client.post(
            "/api/visits/register/",
            {
                "visitor": {"full_name": "Sita Sharma", "phone": "6666666666", "company": "B Ltd"},
                "visit": {
                    "purpose": "Client meeting", "building": self.building.id,
                    "host": self.admin.id, "visit_date": str(date.today()),
                },
            },
            format="json", **h,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        visit_id = resp.json()["visit"]["id"]
        detail = self.client.get(f"/api/visits/{visit_id}/", **h)
        self.assertEqual(detail.status_code, 200, detail.content)

    def test_api_walkin_creates_approved_visit_and_live_pass(self):
        h = jwt_header(self.admin)
        resp = self.client.post(
            "/api/visits/walkin/",
            {
                "visitor": {"full_name": "Ravi Walkin", "phone": "6666666677", "company": "C Ltd"},
                "visit": {
                    "purpose": "Walk-in meeting", "building": self.building.id,
                    "host": self.admin.id, "visit_date": str(date.today()),
                },
            },
            format="json", **h,
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertEqual(data["visit"]["status"], VisitStatus.APPROVED)
        self.assertTrue(data["visit"]["qr"]["is_valid"], "Walk-in pass must be immediately valid")

    def test_api_visit_approve_reject_checkin_checkout(self):
        h = jwt_header(self.admin)
        pending = self.visit
        approve = self.client.post(f"/api/visits/{pending.id}/approve/", {}, format="json", **h)
        self.assertEqual(approve.status_code, 200, approve.content)
        pending.refresh_from_db()
        self.assertEqual(pending.status, VisitStatus.APPROVED)

        checkin = self.client.post(f"/api/visits/{pending.id}/checkin/", {}, format="json", **h)
        self.assertEqual(checkin.status_code, 200, checkin.content)
        pending.refresh_from_db()
        self.assertEqual(pending.status, VisitStatus.CHECKED_IN)

        checkout = self.client.post(f"/api/visits/{pending.id}/checkout/", {}, format="json", **h)
        self.assertEqual(checkout.status_code, 200, checkout.content)
        pending.refresh_from_db()
        self.assertEqual(pending.status, VisitStatus.CHECKED_OUT)

        v2 = Visit.objects.create(
            visitor=self.visitor, organization=self.org, building=self.building,
            host=self.admin, created_by=self.reception, purpose="Sales", visit_date=date.today(),
        )
        reject = self.client.post(
            f"/api/visits/{v2.id}/reject/", {"reason": "N/A"}, format="json", **h
        )
        self.assertEqual(reject.status_code, 200, reject.content)

    # -------------------------------------------------------- server pages



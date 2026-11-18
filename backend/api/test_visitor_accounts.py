"""Self-service visitor accounts: sign-up, sign-in, booking, management, isolation."""

from datetime import date, timedelta

from django.core.cache import cache
from rest_framework.test import APITestCase

from accounts.models import Role, User
from organizations.models import AuditLog, Building, Department, Employee, Organization
from visits.models import QRPass, Visit, VisitSource, VisitStatus, Visitor, VisitorAccount
from visits.services import approve_visit

PASSWORD = "Visitor-Str0ng!Pass"


class VisitorAccountBase(APITestCase):
    def setUp(self):
        # Per-IP throttle counters live in the cache and would otherwise leak
        # across tests (every test signs up from the same loopback address).
        cache.clear()
        self.org = Organization.objects.create(name="Acme Corp", slug="acme", city="Pune")
        self.other = Organization.objects.create(name="Globex", slug="globex", city="Delhi")
        self.building = Building.objects.create(organization=self.org, name="HQ")
        self.dept = Department.objects.create(organization=self.org, name="Engineering")
        self.host = User.objects.create_user(
            email="host@acme.test", password=PASSWORD, full_name="Host Person",
            role=Role.ADMIN, organization=self.org,
        )
        Employee.objects.create(user=self.host, organization=self.org, employee_id="E-1", department=self.dept)

    def signup(self, email="ravi@example.com", phone="9999999999"):
        resp = self.client.post(
            "/api/visitor/auth/register/",
            {"email": email, "password": PASSWORD, "full_name": "Ravi Kumar", "phone": phone, "company": "Acme"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")
        return resp.data

    def booking_payload(self, **overrides):
        payload = {
            "organization": "acme",
            "visit_type": "INTERVIEW",
            "department": self.dept.pk,
            "building": self.building.pk,
            "host": self.host.pk,
            "visit_date": (date.today() + timedelta(days=2)).isoformat(),
            "expected_arrival": "10:00",
            "expected_exit": "10:30",
            "purpose": "Technical Interview",
        }
        payload.update(overrides)
        return payload


class AuthTests(VisitorAccountBase):
    def test_register_login_me_logout(self):
        data = self.signup()
        self.assertEqual(data["account"]["email"], "ravi@example.com")
        self.assertTrue(VisitorAccount.objects.filter(email="ravi@example.com").exists())
        self.assertTrue(AuditLog.objects.filter(action="Visitor account created").exists())
        me = self.client.get("/api/visitor/me/")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["full_name"], "Ravi Kumar")
        # duplicate e-mail
        self.client.credentials()
        dup = self.client.post(
            "/api/visitor/auth/register/",
            {"email": "RAVI@example.com", "password": PASSWORD, "full_name": "X Y", "phone": "9999999999"},
            format="json",
        )
        self.assertEqual(dup.status_code, 400)
        # weak password
        weak = self.client.post(
            "/api/visitor/auth/register/",
            {"email": "w@example.com", "password": "password", "full_name": "X Y", "phone": "9999999999"},
            format="json",
        )
        self.assertEqual(weak.status_code, 400)
        # login
        login = self.client.post("/api/visitor/auth/login/", {"email": "ravi@example.com", "password": PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200)
        token = login.data["token"]
        bad = self.client.post("/api/visitor/auth/login/", {"email": "ravi@example.com", "password": "nope"}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        out = self.client.post("/api/visitor/auth/logout/")
        self.assertEqual(out.status_code, 200)
        self.assertEqual(self.client.get("/api/visitor/me/").status_code, 401)

    def test_lockout_after_failed_attempts(self):
        self.signup()
        self.client.credentials()
        for _ in range(5):
            self.client.post("/api/visitor/auth/login/", {"email": "ravi@example.com", "password": "nope"}, format="json")
        resp = self.client.post("/api/visitor/auth/login/", {"email": "ravi@example.com", "password": PASSWORD}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Too many", resp.data["detail"])

    def test_visitor_token_is_not_a_staff_login(self):
        self.signup()
        for path in ("/api/auth/me/", "/api/visits/", "/api/visitors/", "/api/team/"):
            self.assertEqual(self.client.get(path).status_code, 401, path)

    def test_staff_jwt_is_not_a_visitor_session(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.host).access_token}")
        self.assertEqual(self.client.get("/api/visitor/me/").status_code, 401)

    def test_profile_and_password(self):
        self.signup()
        resp = self.client.patch("/api/visitor/me/", {"company": "Initech", "full_name": "Ravi K"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["company"], "Initech")
        resp = self.client.post("/api/visitor/change-password/", {"current_password": "wrong", "new_password": "New-Str0ng!Pass"}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post("/api/visitor/change-password/", {"current_password": PASSWORD, "new_password": "New-Str0ng!Pass"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.client.credentials()
        self.assertEqual(
            self.client.post("/api/visitor/auth/login/", {"email": "ravi@example.com", "password": "New-Str0ng!Pass"}, format="json").status_code,
            200,
        )


class BookingTests(VisitorAccountBase):
    def test_search_and_context_require_session(self):
        self.assertEqual(self.client.get("/api/visitor/organizations/?q=ac").status_code, 401)
        self.signup()
        resp = self.client.get("/api/visitor/organizations/?q=a")
        self.assertEqual(resp.data, [])
        resp = self.client.get("/api/visitor/organizations/?q=acme")
        self.assertEqual([o["slug"] for o in resp.data], ["acme"])
        resp = self.client.get("/api/visitor/organizations/?q=pune")
        self.assertEqual(len(resp.data), 1)
        ctx = self.client.get("/api/visitor/organizations/acme/")
        self.assertEqual(ctx.status_code, 200)
        self.assertEqual(ctx.data["organization"]["name"], "Acme Corp")
        self.assertEqual(len(ctx.data["departments"]), 1)
        self.assertIn("INTERVIEW", ctx.data["purposes"])
        self.assertEqual(self.client.get("/api/visitor/organizations/nope/").status_code, 404)

    def test_book_creates_pending_visit_linked_to_account(self):
        self.signup()
        resp = self.client.post("/api/visitor/bookings/", self.booking_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        visit = Visit.objects.get(visit_id=resp.data["visit"]["reference"].lower())
        self.assertEqual(visit.status, VisitStatus.PENDING)
        self.assertEqual(visit.source, VisitSource.PUBLIC_BOOKING)
        self.assertEqual(visit.host, self.host)
        self.assertEqual(visit.visitor.account.email, "ravi@example.com")
        self.assertEqual(visit.visitor.organization, self.org)
        self.assertEqual(resp.data["visit"]["organization_slug"], "acme")
        self.assertFalse(QRPass.objects.filter(visit=visit).exists())
        # listed under my bookings
        mine = self.client.get("/api/visitor/bookings/")
        self.assertEqual(len(mine.data["visits"]), 1)
        self.assertEqual(mine.data["visits"][0]["status"], "PENDING")

    def test_booking_validation(self):
        self.signup()
        resp = self.client.post("/api/visitor/bookings/", self.booking_payload(organization="nope"), format="json")
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post("/api/visitor/bookings/", self.booking_payload(purpose="Not a real purpose"), format="json")
        self.assertEqual(resp.status_code, 400)
        foreign = Department.objects.create(organization=self.other, name="Ops")
        resp = self.client.post("/api/visitor/bookings/", self.booking_payload(department=foreign.pk), format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post("/api/visitor/bookings/", self.booking_payload(visit_date=(date.today() - timedelta(days=1)).isoformat()), format="json")
        self.assertEqual(resp.status_code, 400)

    def test_phone_owned_by_another_account_is_refused(self):
        self.signup(email="first@example.com", phone="9999999999")
        self.assertEqual(self.client.post("/api/visitor/bookings/", self.booking_payload(), format="json").status_code, 201)
        self.client.credentials()
        self.signup(email="second@example.com", phone="9999999999")
        resp = self.client.post("/api/visitor/bookings/", self.booking_payload(expected_arrival="11:00", expected_exit="11:30"), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("another visitor account", resp.data["detail"])

    def test_existing_unclaimed_visitor_record_is_claimed(self):
        existing = Visitor.objects.create(organization=self.org, full_name="Ravi Kumar", phone="9999999999")
        self.signup()
        self.assertEqual(self.client.post("/api/visitor/bookings/", self.booking_payload(), format="json").status_code, 201)
        existing.refresh_from_db()
        self.assertEqual(existing.account.email, "ravi@example.com")

    def test_manage_booking_and_isolation(self):
        self.signup()
        created = self.client.post("/api/visitor/bookings/", self.booking_payload(), format="json").data["visit"]
        vid = created["id"]
        detail = self.client.get(f"/api/visitor/bookings/{vid}/")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.data["can_reschedule"])
        # availability for the host
        day = (date.today() + timedelta(days=3)).isoformat()
        avail = self.client.get(f"/api/visitor/bookings/{vid}/availability/?date={day}")
        self.assertEqual(avail.status_code, 200)
        self.assertTrue(avail.data["slots"])
        slot = avail.data["slots"][0]
        res = self.client.post(f"/api/visitor/bookings/{vid}/reschedule/", {"visit_date": day, "expected_arrival": slot["start"], "expected_exit": slot["end"]}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["visit"]["visit_date"], day)
        # approve by staff -> pass visible to the visitor
        visit = Visit.objects.get(pk=vid)
        ok, _ = approve_visit(visit, self.host)
        self.assertTrue(ok)
        detail = self.client.get(f"/api/visitor/bookings/{vid}/")
        self.assertEqual(detail.data["status"], "APPROVED")
        self.assertIsNotNone(detail.data["qr"])
        self.assertTrue(detail.data["qr"]["is_valid"])
        # another account cannot see or touch it
        self.client.credentials()
        self.signup(email="other@example.com", phone="8888888888")
        self.assertEqual(self.client.get(f"/api/visitor/bookings/{vid}/").status_code, 404)
        self.assertEqual(self.client.post(f"/api/visitor/bookings/{vid}/cancel/", {}, format="json").status_code, 404)
        self.assertEqual(len(self.client.get("/api/visitor/bookings/").data["visits"]), 0)
        # owner cancels -> pass voided
        self.client.credentials()
        login = self.client.post("/api/visitor/auth/login/", {"email": "ravi@example.com", "password": PASSWORD}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['token']}")
        res = self.client.post(f"/api/visitor/bookings/{vid}/cancel/", {"reason": "Plans changed"}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data["visit"]["status"], "CANCELLED")
        self.assertFalse(QRPass.objects.filter(visit_id=vid).exists())
        self.assertEqual(self.client.post(f"/api/visitor/bookings/{vid}/arriving/", {}, format="json").status_code, 400)

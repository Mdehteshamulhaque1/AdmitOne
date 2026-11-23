"""6-month student passes: issuing (admins only), gate IN/OUT rules, renew/revoke."""

import io
import shutil
import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import Role, User
from organizations.models import AuditLog, Organization
from visits import student_passes as svc
from visits.models import StudentPass, StudentPassScan, Visitor, VisitorAccount

_MEDIA = tempfile.mkdtemp(prefix="admitone-sp-media-")
IST = ZoneInfo("Asia/Kolkata")


def photo():
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (20, 80, 200)).save(buf, format="PNG")
    return SimpleUploadedFile("face.png", buf.getvalue(), content_type="image/png")


def next_weekday(d):
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


class DateMathTests(TestCase):
    def test_six_months_and_month_end_clamping(self):
        self.assertEqual(svc.end_of_term(date(2026, 1, 15)), date(2026, 7, 14))
        self.assertEqual(svc.add_months(date(2026, 8, 31), 6), date(2027, 2, 28))
        self.assertEqual(svc.add_months(date(2027, 8, 31), 6), date(2028, 2, 29))
        self.assertEqual(svc.add_months(date(2026, 11, 30), 3), date(2027, 2, 28))


@override_settings(MEDIA_ROOT=_MEDIA, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class StudentPassBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="Pyspiders", slug="pyspiders", timezone="Asia/Kolkata",
                                               working_hours_start="09:00", working_hours_end="18:00")
        self.other = Organization.objects.create(name="Other Institute", slug="other", timezone="Asia/Kolkata")
        mk = lambda email, role, org=self.org: User.objects.create_user(email=email, password="Str0ng!Pass1", full_name=email.split("@")[0].title(), role=role, organization=org)
        self.admin = mk("admin@py.test", Role.ADMIN)
        self.desk = mk("desk@py.test", Role.RECEPTIONIST)
        self.guard = mk("gate@py.test", Role.SECURITY)
        self.other_guard = mk("gate@other.test", Role.SECURITY, self.other)

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def issue_payload(self, **over):
        data = {
            "full_name": "Ravi Kumar", "phone": "9876543210", "email": "ravi@example.com",
            "admission_number": "pys-2026-001", "course": "Java Full Stack", "batch": "Jan 2027",
            "document_type": "AADHAAR", "document_number": "1234 5678 9012", "photo": photo(),
        }
        data.update(over)
        return data

    def make_pass(self, start=None, org=None, phone="9876500000", admission="PYS-1"):
        org = org or self.org
        visitor = Visitor.objects.create(organization=org, full_name="Asha Singh", phone=phone, category="STUDENT")
        return svc.issue_pass(org, visitor=visitor, admission_number=admission, course="Python", valid_from=start or date.today())


class IssueTests(StudentPassBase):
    def test_admin_issues_a_six_month_pass_and_it_is_emailed(self):
        resp = self.client_for(self.admin).post("/api/student-passes/", self.issue_payload(), format="multipart")
        self.assertEqual(resp.status_code, 201, resp.data)
        sp = StudentPass.objects.get()
        self.assertEqual(sp.admission_number, "PYS-2026-001")  # normalised
        self.assertEqual(sp.valid_until, svc.end_of_term(sp.valid_from))
        self.assertEqual(resp.data["status"], "ACTIVE")
        self.assertTrue(resp.data["payload"].startswith("SP|"))
        self.assertTrue(resp.data["emailed"])
        v = sp.visitor
        self.assertEqual((v.category, v.document_type, v.document_number), ("STUDENT", "AADHAAR", "123456789012"))
        self.assertTrue(v.photo.name.startswith("visitor_photos/"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("student pass", mail.outbox[0].subject)
        self.assertTrue(AuditLog.objects.filter(action="Student pass issued").exists())

    def test_validation(self):
        c = self.client_for(self.admin)
        self.assertEqual(c.post("/api/student-passes/", self.issue_payload(), format="multipart").status_code, 201)
        cases = [
            ({"admission_number": "PYS-2026-001", "phone": "9000000001"}, "already exists"),
            ({"admission_number": "X2", "phone": "9000000002", "document_number": "12345"}, "12 digits"),
            ({"admission_number": "X3", "phone": "9000000003", "photo": ""}, "photo"),
            ({"admission_number": "X4"}, "already has an active pass"),  # same phone as the first student
            ({"admission_number": "X5", "phone": "12"}, "at least 7 digits"),
        ]
        for over, needle in cases:
            payload = self.issue_payload(**over)
            if payload.get("photo") == "":
                payload.pop("photo")
            resp = c.post("/api/student-passes/", payload, format="multipart")
            self.assertEqual(resp.status_code, 400, over)
            self.assertIn(needle, str(resp.data), over)

    def test_only_admins_manage_passes(self):
        for user in (self.desk, self.guard):
            c = self.client_for(user)
            self.assertEqual(c.get("/api/student-passes/").status_code, 403)
            self.assertEqual(c.post("/api/student-passes/", self.issue_payload(), format="multipart").status_code, 403)

    def test_tenant_isolation_in_list_and_detail(self):
        mine = self.make_pass()
        theirs = self.make_pass(org=self.other, admission="OTH-1")
        c = self.client_for(self.admin)
        ids = [p["id"] for p in c.get("/api/student-passes/").data["results"]]
        self.assertEqual(ids, [mine.pk])
        self.assertEqual(c.get(f"/api/student-passes/{theirs.pk}/").status_code, 404)

    def test_renew_and_revoke(self):
        sp = self.make_pass()
        c = self.client_for(self.admin)
        old_end = sp.valid_until
        resp = c.post(f"/api/student-passes/{sp.pk}/revoke/", {"reason": "Left the course"}, format="json")
        self.assertEqual(resp.data["status"], "REVOKED")
        resp = c.post(f"/api/student-passes/{sp.pk}/renew/", {}, format="json")
        self.assertEqual(resp.data["status"], "ACTIVE")
        sp.refresh_from_db()
        self.assertEqual(sp.valid_until, svc.add_months(old_end + timedelta(days=1), 6) - timedelta(days=1))
        self.assertEqual(sp.renewed_count, 1)


class GateScanTests(StudentPassBase):
    def setUp(self):
        super().setUp()
        self.day = next_weekday(date.today() + timedelta(days=1))
        self.sp = self.make_pass(start=self.day)
        self.gate = self.client_for(self.guard)

    def at(self, hh, mm=0, day=None, plus_seconds=0):
        t = datetime(*(day or self.day).timetuple()[:3], hh, mm, tzinfo=IST) + timedelta(seconds=plus_seconds)
        return patch("django.utils.timezone.now", return_value=t)

    def scan(self, payload=None, client=None, dry_run=False):
        return (client or self.gate).post("/api/visits/scan/", {"payload": payload or self.sp.payload, "dry_run": dry_run}, format="json")

    def test_in_out_in_and_double_scan_guard(self):
        with self.at(9, 5):
            r = self.scan()
            self.assertEqual((r.status_code, r.data["direction"], r.data["kind"]), (200, "IN", "student"))
            self.assertEqual(r.data["student_pass"]["admission_number"], "PYS-1")
        with self.at(9, 5, plus_seconds=20):
            r = self.scan()
            self.assertEqual(r.status_code, 400)
            self.assertIn("a moment ago", r.data["detail"])
        with self.at(13, 0):
            self.assertEqual(self.scan().data["direction"], "OUT")
        with self.at(14, 0):
            self.assertEqual(self.scan().data["direction"], "IN")
        self.assertEqual(list(StudentPassScan.objects.order_by("scanned_at").values_list("direction", flat=True)), ["IN", "OUT", "IN"])

    def test_entry_only_in_hours_but_exit_always(self):
        with self.at(8, 0):
            r = self.scan()
            self.assertEqual(r.status_code, 400)
            self.assertIn("institute hours", r.data["detail"])
        with self.at(8, 40):  # within the 30-minute early window
            self.assertEqual(self.scan().data["direction"], "IN")
        with self.at(20, 0):  # late exit is still recorded
            self.assertEqual(self.scan().data["direction"], "OUT")

    def test_open_from_midnight_does_not_wrap_round(self):
        # Regression: 30-minute early allowance before a 00:00 opening wrapped to 23:30.
        self.org.working_hours_start, self.org.working_hours_end = "00:00", "23:59"
        self.org.save()
        with self.at(15, 0):
            self.assertEqual(self.scan().data["direction"], "IN")

    def test_closed_day(self):
        self.org.weekly_working_hours = {str(d): ([{"start": "09:00", "end": "18:00"}] if d != self.day.weekday() else None) for d in range(7)}
        self.org.save()
        with self.at(10, 0):
            r = self.scan()
        self.assertEqual(r.status_code, 400)
        self.assertIn("not a working day", r.data["detail"])

    def test_refusals(self):
        with self.at(10, 0, day=self.day - timedelta(days=1)):
            self.assertIn("starts on", self.scan().data["detail"])
        with self.at(10, 0, day=self.sp.valid_until + timedelta(days=1)):
            self.assertIn("expired", self.scan().data["detail"])
        token, sig = self.sp.payload.split("|")[1:]
        with self.at(10, 0):
            self.assertIn("tampered", self.scan(f"SP|{token}|{'0' * 64}").data["detail"])
            self.assertIn("Unknown pass", self.scan(client=self.client_for(self.other_guard)).data["detail"])
            self.assertIn("Unknown pass", self.scan("SP|not-a-uuid|x").data["detail"])
            r = self.scan(dry_run=True)
            self.assertEqual((r.status_code, r.data["direction"]), (200, "IN"))
            self.assertFalse(StudentPassScan.objects.exists())  # dry run records nothing
            svc.revoke_pass(self.sp, reason="Fees pending")
            r = self.scan()
            self.assertEqual(r.status_code, 400)
            self.assertIn("revoked: Fees pending", r.data["detail"])

    def test_reception_cannot_scan(self):
        with self.at(10, 0):
            self.assertEqual(self.scan(client=self.client_for(self.desk)).status_code, 403)

    def test_attendance_endpoint(self):
        with self.at(9, 30):
            self.scan()
        r = self.client_for(self.admin).get(f"/api/student-passes/attendance/?date={self.day.isoformat()}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([(s["admission_number"], s["direction"]) for s in r.data["scans"]], [("PYS-1", "IN")])


class VisitorPortalTests(StudentPassBase):
    def test_student_sees_own_pass_with_qr(self):
        sp = self.make_pass()
        account = VisitorAccount.objects.create(email="asha@example.com", full_name="Asha Singh", phone="9876500000")
        account.set_password("Str0ng!Pass1")
        account.save()
        sp.visitor.account = account
        sp.visitor.save()
        c = APIClient()
        login = c.post("/api/visitor/auth/login/", {"email": "asha@example.com", "password": "Str0ng!Pass1"}, format="json")
        self.assertEqual(login.status_code, 200, login.data)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['token']}")
        r = c.get("/api/visitor/student-pass/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["passes"][0]["admission_number"], "PYS-1")
        self.assertEqual(r.data["passes"][0]["payload"], sp.payload)

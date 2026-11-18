"""Training-centre flow: visitor catalogue, student profile, rooms, room
assignment on approval and room attendance scans."""

from datetime import date, timedelta

from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Role, User
from organizations.models import AuditLog, Building, Floor, Organization
from visits.models import Room, RoomAttendance, Visit, VisitStatus, VisitType, Visitor
from visits.purposes import TRAINING_CENTRE_CATALOGUE
from visits.services import approve_visit, check_in

PASSWORD = "Str0ng!Pass-2024"


def auth(client, user):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")


class RoomsBase(APITestCase):
    def setUp(self):
        cache.clear()
        self.org = Organization.objects.create(name="QSpiders Noida", slug="qspiders-noida", city="Noida")
        self.other = Organization.objects.create(name="Globex", slug="globex")
        self.building = Building.objects.create(organization=self.org, name="Sector 16 Tower", floors=4)
        self.f3 = Floor.objects.create(building=self.building, name="3rd Floor", level=3)
        self.f4 = Floor.objects.create(building=self.building, name="4th Floor", level=4)
        self.other_building = Building.objects.create(organization=self.other, name="Globex HQ")
        self.admin = self._user("admin@qs.test", Role.ADMIN)
        self.security = self._user("gate@qs.test", Role.SECURITY)
        self.reception = self._user("desk@qs.test", Role.RECEPTIONIST)
        self.outsider = self._user("admin@globex.test", Role.ADMIN, org=self.other)
        self.lab = Room.objects.create(
            building=self.building, floor=self.f3, number="301", name="Java Lab", room_type="LAB", capacity=40
        )
        self.hall = Room.objects.create(
            building=self.building, floor=self.f4, number="401", name="Placement Hall", room_type="PLACEMENT_HALL"
        )
        self.foreign_room = Room.objects.create(building=self.other_building, number="G-1")
        self.visitor = Visitor.objects.create(
            organization=self.org, full_name="Ravi Kumar", phone="9999999999", category="STUDENT"
        )

    def _user(self, email, role, org=None):
        return User.objects.create_user(
            email=email, password=PASSWORD, full_name=email.split("@")[0],
            role=role, organization=org or self.org,
        )

    def _pending(self, **kw):
        defaults = dict(
            visitor=self.visitor, organization=self.org, building=self.building, host=self.admin,
            created_by=self.reception, purpose="Lab practice", visit_date=date.today(),
            visit_type=VisitType.TRAINING_WORKSHOP, visitor_category="STUDENT",
        )
        defaults.update(kw)
        return Visit.objects.create(**defaults)

    def _checked_in(self):
        visit = self._pending()
        ok, _ = approve_visit(visit, self.admin)
        assert ok
        ok, _ = check_in(visit, self.security, via_qr=True)
        assert ok
        visit.refresh_from_db()
        return visit

    def _pass(self, visit):
        return f"{visit.qr_pass.token}|{visit.qr_pass.signature}"


# ------------------------------------------------------------------ rooms CRUD


class RoomCrudTests(RoomsBase):
    def test_admin_creates_room_in_own_building(self):
        auth(self.client, self.admin)
        resp = self.client.post("/api/rooms/", {
            "building": self.building.pk, "floor": self.f4.pk, "number": "402",
            "name": "Grooming Room", "room_type": "GROOMING_ROOM", "capacity": 25,
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["label"], "402 Grooming Room (Grooming room)")
        self.assertEqual(resp.data["floor_name"], "4th Floor")
        self.assertTrue(AuditLog.objects.filter(action="Room created", organization=self.org).exists())

    def test_room_in_foreign_building_rejected(self):
        auth(self.client, self.admin)
        resp = self.client.post("/api/rooms/", {"building": self.other_building.pk, "number": "9"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("building", resp.data)

    def test_floor_must_belong_to_building(self):
        other_floor = Floor.objects.create(building=self.other_building, name="G", level=0)
        auth(self.client, self.admin)
        resp = self.client.post("/api/rooms/", {
            "building": self.building.pk, "floor": other_floor.pk, "number": "9",
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("floor", resp.data)

    def test_duplicate_number_in_building_rejected(self):
        auth(self.client, self.admin)
        resp = self.client.post("/api/rooms/", {"building": self.building.pk, "number": "301"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("number", resp.data)

    def test_list_scoped_and_filterable(self):
        auth(self.client, self.security)
        resp = self.client.get("/api/rooms/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({r["number"] for r in resp.data}, {"301", "401"})
        resp = self.client.get(f"/api/rooms/?building={self.other_building.pk}")
        self.assertEqual(resp.data, [])
        auth(self.client, self.outsider)
        resp = self.client.get("/api/rooms/")
        self.assertEqual([r["number"] for r in resp.data], ["G-1"])

    def test_security_cannot_write_rooms(self):
        auth(self.client, self.security)
        resp = self.client.post("/api/rooms/", {"building": self.building.pk, "number": "5"}, format="json")
        self.assertEqual(resp.status_code, 403)
        resp = self.client.delete(f"/api/rooms/{self.lab.pk}/")
        self.assertEqual(resp.status_code, 403)

    def test_cannot_touch_foreign_room(self):
        auth(self.client, self.admin)
        resp = self.client.patch(f"/api/rooms/{self.foreign_room.pk}/", {"name": "x"}, format="json")
        self.assertEqual(resp.status_code, 404)


class FloorSyncTests(RoomsBase):
    def test_building_floors_count_creates_floor_rows(self):
        auth(self.client, self.admin)
        resp = self.client.post("/api/buildings/", {"name": "Annex", "floors": 3}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual([f["name"] for f in resp.data["floor_list"]], ["Ground floor", "1st floor", "2nd floor"])
        bid = resp.data["id"]
        # shrinking keeps a floor that has a room on it
        Room.objects.create(building_id=bid, floor_id=resp.data["floor_list"][2]["id"], number="201")
        resp = self.client.patch(f"/api/buildings/{bid}/", {"floors": 1}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual([f["level"] for f in resp.data["floor_list"]], [1, 3])
        self.assertEqual(resp.data["room_count"], 1)


# ------------------------------------------------------------- the catalogue


class CatalogueTests(RoomsBase):
    def test_defaults_served_until_customised(self):
        auth(self.client, self.admin)
        resp = self.client.get("/api/organizations/me/")
        self.assertEqual(resp.status_code, 200)
        keys = [c["key"] for c in resp.data["visitor_catalogue"]["categories"]]
        self.assertEqual(keys, [c["key"] for c in TRAINING_CENTRE_CATALOGUE["categories"]])

    def test_patch_catalogue_validated_and_applied(self):
        auth(self.client, self.admin)
        bad = {"visitor_policies": {"visitor_catalogue": {"categories": [{"key": "", "label": "x"}]}}}
        resp = self.client.patch("/api/organizations/me/", bad, format="json")
        self.assertEqual(resp.status_code, 400, resp.content)

        good = {"visitor_policies": {"visitor_catalogue": {"categories": [
            {"key": "member", "label": "Gym member", "purposes": [
                {"label": "Workout", "visit_type": "GUEST", "room_type": "OTHER"},
            ]},
        ]}}}
        resp = self.client.patch("/api/organizations/me/", good, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        cats = resp.data["visitor_catalogue"]["categories"]
        self.assertEqual(cats[0]["key"], "MEMBER")
        # "Other" is always appended so the free-text escape hatch exists.
        self.assertEqual([p["label"] for p in cats[0]["purposes"]], ["Workout", "Other"])

        # the booking context for visitors now reflects it
        self.client.credentials()
        signup = self.client.post("/api/visitor/auth/register/", {
            "email": "s@example.com", "password": PASSWORD, "full_name": "Sita Devi", "phone": "9888888888",
        }, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {signup.data['token']}")
        ctx = self.client.get("/api/visitor/organizations/qspiders-noida/")
        self.assertEqual([c["key"] for c in ctx.data["visitor_categories"]], ["MEMBER"])

    def test_empty_catalogue_restores_defaults(self):
        self.org.visitor_policies = {"visitor_catalogue": {"categories": [
            {"key": "X", "label": "X", "purposes": []}]}}
        self.org.save()
        auth(self.client, self.admin)
        resp = self.client.patch(
            "/api/organizations/me/", {"visitor_policies": {"visitor_catalogue": {}}}, format="json"
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.org.refresh_from_db()
        self.assertNotIn("visitor_catalogue", self.org.visitor_policies)
        self.assertEqual(resp.data["visitor_catalogue"]["categories"][0]["key"], "STUDENT")


# -------------------------------------------------- visitor profile + booking


class StudentBookingTests(RoomsBase):
    def _signup(self):
        resp = self.client.post("/api/visitor/auth/register/", {
            "email": "ravi@example.com", "password": PASSWORD, "full_name": "Ravi Kumar",
            "phone": "9777777777", "category": "student", "state": "Bihar",
            "university": "Patna University", "qualification": "B.Tech (CSE)", "passing_year": 2024,
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['token']}")
        return resp.data

    def test_profile_fields_saved_and_shown(self):
        data = self._signup()
        self.assertEqual(data["account"]["category"], "STUDENT")
        self.assertEqual(data["account"]["passing_year"], 2024)
        resp = self.client.patch("/api/visitor/me/", {"state": "Uttar Pradesh", "passing_year": 2025}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["state"], "Uttar Pradesh")
        self.assertEqual(resp.data["passing_year"], 2025)
        self.assertEqual(resp.data["university"], "Patna University")

    def test_booking_by_category_and_purpose(self):
        self._signup()
        payload = {
            "organization": "qspiders-noida", "category": "STUDENT", "purpose": "Pool placement drive",
            "building": self.building.pk, "floor": self.f4.pk, "host": self.admin.pk,
            "visit_date": (date.today() + timedelta(days=2)).isoformat(),
            "expected_arrival": "10:00", "expected_exit": "13:00",
        }
        resp = self.client.post("/api/visitor/bookings/", payload, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["visit"]["visit_type"], VisitType.CAMPUS_PLACEMENT)
        self.assertEqual(resp.data["visit"]["visitor_category"], "STUDENT")
        visit = Visit.objects.get(pk=resp.data["visit"]["id"])
        self.assertEqual(visit.visitor.state, "Bihar")
        self.assertEqual(visit.visitor.qualification, "B.Tech (CSE)")
        self.assertEqual(visit.visitor.passing_year, 2024)

        # purpose outside the category's list is refused
        resp = self.client.post("/api/visitor/bookings/", {**payload, "purpose": "Workout"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("purpose", resp.data["detail"])
        resp = self.client.post("/api/visitor/bookings/", {**payload, "category": "ALIEN"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("category", resp.data["detail"])

    def test_account_category_used_when_none_sent(self):
        self._signup()
        resp = self.client.post("/api/visitor/bookings/", {
            "organization": "qspiders-noida", "purpose": "Mock interview",
            "building": self.building.pk, "host": self.admin.pk,
            "visit_date": (date.today() + timedelta(days=1)).isoformat(),
            "expected_arrival": "11:00", "expected_exit": "11:30",
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data["visit"]["visit_type"], VisitType.INTERVIEW)

    def test_public_booking_accepts_category(self):
        resp = self.client.get("/api/public/booking/qspiders-noida/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["visitor_categories"][0]["key"], "STUDENT")
        resp = self.client.post("/api/public/booking/qspiders-noida/", {
            "visitor": {"full_name": "Asha", "phone": "9666666666"},
            "category": "PARENT", "purpose": "Other", "purpose_other": "Meet the counsellor",
            "building": self.building.pk, "host": self.admin.pk,
            "visit_date": (date.today() + timedelta(days=1)).isoformat(),
            "expected_arrival": "11:00", "expected_exit": "11:30",
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        visit = Visit.objects.get(visitor__phone="9666666666")
        self.assertEqual(visit.visitor_category, "PARENT")
        self.assertEqual(visit.purpose, "Meet the counsellor")


# ----------------------------------------------------------- room assignment


class AssignRoomTests(RoomsBase):
    def test_approve_with_room_sets_room_floor_building(self):
        visit = self._pending(building=None)
        auth(self.client, self.admin)
        resp = self.client.post(f"/api/visits/{visit.pk}/approve/", {"room": self.hall.pk}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["visit"]["status"], VisitStatus.APPROVED)
        self.assertEqual(resp.data["visit"]["room"], self.hall.pk)
        self.assertEqual(resp.data["visit"]["floor_name"], "4th Floor")
        self.assertEqual(resp.data["visit"]["building_name"], "Sector 16 Tower")
        self.assertTrue(AuditLog.objects.filter(action="Room assigned", entity_id=str(visit.visit_id)).exists())

    def test_approve_with_foreign_room_refuses_without_approving(self):
        visit = self._pending()
        auth(self.client, self.admin)
        resp = self.client.post(f"/api/visits/{visit.pk}/approve/", {"room": self.foreign_room.pk}, format="json")
        self.assertEqual(resp.status_code, 400)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.PENDING)
        self.assertIsNone(visit.room_id)

    def test_assign_and_clear(self):
        visit = self._pending()
        auth(self.client, self.admin)
        resp = self.client.post(f"/api/visits/{visit.pk}/assign-room/", {"room": self.lab.pk}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data["visit"]["room_label"], "301 Java Lab (Lab)")
        resp = self.client.post(f"/api/visits/{visit.pk}/assign-room/", {"room": None}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIsNone(resp.data["visit"]["room"])
        self.assertTrue(AuditLog.objects.filter(action="Room cleared").exists())

    def test_security_cannot_assign(self):
        visit = self._pending()
        auth(self.client, self.security)
        resp = self.client.post(f"/api/visits/{visit.pk}/assign-room/", {"room": self.lab.pk}, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_visits_filter_by_room(self):
        a = self._pending(room=self.lab)
        self._pending(room=self.hall)
        auth(self.client, self.admin)
        resp = self.client.get(f"/api/visits/?room={self.lab.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([v["id"] for v in resp.data["results"]], [a.pk])


# ----------------------------------------------------------- room attendance


class RoomScanTests(RoomsBase):
    def test_scan_records_attendance_repeatedly_across_rooms(self):
        visit = self._checked_in()
        auth(self.client, self.security)
        resp = self.client.post("/api/visits/room-scan/", {
            "payload": self._pass(visit), "room": self.lab.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data["ok"])
        self.assertEqual(resp.data["attendance"]["room_number"], "301")
        self.assertEqual(resp.data["visit"]["attendance_count"], 1)

        # same room within a minute: double tap, not a second row
        resp = self.client.post("/api/visits/room-scan/", {
            "payload": self._pass(visit), "room": self.lab.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(RoomAttendance.objects.filter(visit=visit).count(), 1)

        # a different room is a new record even though the pass is "used"
        resp = self.client.post("/api/visits/room-scan/", {
            "payload": self._pass(visit), "room": self.hall.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(RoomAttendance.objects.filter(visit=visit).count(), 2)
        self.assertEqual(AuditLog.objects.filter(action="Room attendance recorded").count(), 2)

        auth(self.client, self.admin)
        resp = self.client.get(f"/api/visits/{visit.pk}/attendance/")
        self.assertEqual([r["room_number"] for r in resp.data["results"]], ["401", "301"])
        # explicit date: "today" on the server is the workspace's UTC date,
        # which differs from the local date for a few hours after midnight
        day = visit.visit_date.isoformat()
        resp = self.client.get(f"/api/attendance/?date={day}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data["results"]), 2)
        resp = self.client.get(f"/api/attendance/?date={day}&room={self.hall.pk}")
        self.assertEqual(len(resp.data["results"]), 1)
        resp = self.client.get(f"/api/attendance/?date={(date.today() - timedelta(days=1)).isoformat()}")
        self.assertEqual(len(resp.data["results"]), 0)

    def test_requires_gate_check_in_first(self):
        visit = self._pending()
        approve_visit(visit, self.admin)
        visit.refresh_from_db()
        auth(self.client, self.security)
        resp = self.client.post("/api/visits/room-scan/", {
            "payload": self._pass(visit), "room": self.lab.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("not checked in", resp.data["detail"])
        self.assertFalse(RoomAttendance.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action="Room scan rejected").exists())

    def test_dry_run_recognises_without_recording(self):
        visit = self._checked_in()
        auth(self.client, self.security)
        resp = self.client.post("/api/visits/room-scan/", {
            "payload": self._pass(visit), "room": self.lab.pk, "dry_run": True,
        }, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(resp.data["dry_run"])
        self.assertFalse(RoomAttendance.objects.exists())

    def test_tampered_or_foreign_pass_is_unknown(self):
        visit = self._checked_in()
        token = visit.qr_pass.token
        auth(self.client, self.security)
        resp = self.client.post("/api/visits/room-scan/", {
            "payload": f"{token}|deadbeef", "room": self.lab.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["detail"], "Unknown pass - not registered in system")
        # the outsider's scanner cannot see our visitor at all
        auth(self.client, self.outsider)
        resp = self.client.post("/api/visits/room-scan/", {
            "payload": self._pass(visit), "room": self.foreign_room.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(resp.data["visit"])

    def test_room_must_be_ours_and_scanner_needs_scan_qr(self):
        visit = self._checked_in()
        auth(self.client, self.security)
        resp = self.client.post("/api/visits/room-scan/", {
            "payload": self._pass(visit), "room": self.foreign_room.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("room", resp.data["detail"].lower())
        auth(self.client, self.reception)
        resp = self.client.post("/api/visits/room-scan/", {
            "payload": self._pass(visit), "room": self.lab.pk,
        }, format="json")
        self.assertEqual(resp.status_code, 403)

    def test_attendance_report_requires_view_reports(self):
        self._checked_in()
        auth(self.client, self.outsider)
        resp = self.client.get("/api/attendance/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["results"], [])

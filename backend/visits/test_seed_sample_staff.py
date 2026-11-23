from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import Role, User
from organizations.models import Department, Organization


class SeedSampleStaffTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Pyspiders", slug="pyspiders")
        self.admin = User.objects.create_user(email="admin@py.test", password="Str0ng!Pass1", full_name="Ehtesham", role=Role.ADMIN, organization=self.org)

    def run_cmd(self, *args):
        call_command("seed_sample_staff", "pyspiders", *args, stdout=StringIO())

    def test_hosts_appear_with_designations_and_departments(self):
        self.run_cmd()
        self.run_cmd()  # idempotent
        hosts = APIClient().get("/api/public/booking/pyspiders/hosts/").data
        by_name = {h["name"]: h["designation"] for h in hosts}
        self.assertEqual(by_name["Pooja Mishra"], "Student Counsellor")
        self.assertEqual(by_name["Neha Sharma"], "HR Manager")
        self.assertEqual(len([h for h in hosts if h["name"] != "Ehtesham"]), 6)
        self.assertEqual(Department.objects.filter(organization=self.org).count(), 5)
        training = Department.objects.get(organization=self.org, name="Training")
        trainers = APIClient().get(f"/api/public/booking/pyspiders/hosts/?department={training.pk}").data
        self.assertEqual(sorted(h["name"] for h in trainers), ["Amit Verma", "Sana Khan"])
        for u in User.objects.filter(email__endswith="@pyspiders-staff.test"):
            self.assertFalse(u.has_usable_password())

    def test_remove_keeps_real_staff(self):
        self.run_cmd()
        self.run_cmd("--remove")
        self.assertEqual(list(User.objects.filter(organization=self.org).values_list("email", flat=True)), ["admin@py.test"])

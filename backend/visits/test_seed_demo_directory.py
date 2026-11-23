from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from organizations.models import Building, Floor, Organization


class SeedDemoDirectoryTests(TestCase):
    def _run(self, *args):
        call_command("seed_demo_directory", *args, stdout=StringIO())

    def test_seed_is_idempotent_and_bookable(self):
        real = Organization.objects.create(name="Real Co", slug="real-co")
        self._run()
        self._run()  # second run adds nothing
        demo = Organization.objects.filter(slug__startswith="demo-")
        self.assertEqual(demo.count(), 20)
        self.assertEqual(User.objects.filter(email__endswith="@demo.admitone.test").count(), 20)

        names = set(Building.objects.filter(organization__in=demo).values_list("name", flat=True))
        self.assertEqual(names, {"A1", "A2", "A3", "B1", "B2", "B3"})
        for building in Building.objects.filter(organization__in=demo):
            self.assertEqual(building.floor_set.count(), building.floors)
            self.assertGreaterEqual(building.floors, 1)

        # Every demo company has a host the public booking flow can offer.
        client = APIClient()
        for org in demo:
            resp = client.get(f"/api/public/booking/{org.slug}/hosts/")
            self.assertEqual(resp.status_code, 200, resp.data)
            self.assertEqual(len(resp.data), 1, org.slug)
            self.assertFalse(User.objects.get(pk=resp.data[0]["id"]).has_usable_password())

        self.assertTrue(Organization.objects.filter(pk=real.pk).exists())

    def test_remove_deletes_only_demo_data(self):
        real = Organization.objects.create(name="Real Co", slug="real-co")
        Building.objects.create(organization=real, name="HQ")
        self._run()
        self._run("--remove")
        self.assertFalse(Organization.objects.filter(slug__startswith="demo-").exists())
        self.assertFalse(User.objects.filter(email__endswith="@demo.admitone.test").exists())
        self.assertFalse(Floor.objects.filter(building__organization__slug__startswith="demo-").exists())
        self.assertTrue(Building.objects.filter(organization=real).exists())

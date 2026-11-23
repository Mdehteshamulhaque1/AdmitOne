"""Fill the visitor booking directory with demo companies.

Creates 20 fictional companies (slug prefix ``demo-``), each with buildings
named A1, A2, A3, B1, B2, B3 (two to six of them) and a few floors per
building, plus one bookable front-office host so the whole booking wizard can
be tried end to end. Running it again changes nothing that already exists.

    python manage.py seed_demo_directory           # add the demo companies
    python manage.py seed_demo_directory --remove  # delete them again

Demo hosts get an unusable password (nobody can sign in as them) and an
``@demo.admitone.test`` address, which never receives mail.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import Role, User
from api.management_views import sync_floors
from organizations.models import Building, Department, Employee, Organization

SLUG_PREFIX = "demo-"
EMAIL_DOMAIN = "demo.admitone.test"
BUILDING_NAMES = ["A1", "A2", "A3", "B1", "B2", "B3"]

# (name, city, tagline, host name) -- all fictional.
COMPANIES = [
    ("Apex Softech", "Noida", "Software services", "Riya Malhotra"),
    ("BluePeak Solutions", "Gurugram", "Cloud consulting", "Arjun Mehta"),
    ("Crestline Infotech", "Bengaluru", "Product engineering", "Kavya Rao"),
    ("Deltaforge Systems", "Pune", "Embedded systems", "Rohan Kulkarni"),
    ("Evergreen Analytics", "Hyderabad", "Data and analytics", "Sneha Reddy"),
    ("Falcon Edge Technologies", "Chennai", "Cybersecurity", "Vikram Iyer"),
    ("Greenleaf Digital", "Kolkata", "Digital marketing", "Ananya Bose"),
    ("Horizon Learning Academy", "Lucknow", "IT training centre", "Faizan Siddiqui"),
    ("Indigo Bay Networks", "Mumbai", "Networking", "Pooja Desai"),
    ("Jupiter Fintech", "Mumbai", "Payments", "Karan Shah"),
    ("Keystone Engineering", "Ahmedabad", "Industrial design", "Neha Patel"),
    ("Lotus Health Systems", "Jaipur", "Healthcare software", "Aditya Sharma"),
    ("Meridian Logistics", "Indore", "Supply chain", "Simran Kaur"),
    ("Nimbus Cloudworks", "Bengaluru", "Cloud hosting", "Rahul Nair"),
    ("Orbit Mobility", "Chandigarh", "EV software", "Harpreet Singh"),
    ("Pinnacle Skills Institute", "Patna", "Placement training", "Ayesha Khan"),
    ("Quantum Leap Labs", "Hyderabad", "AI research", "Sai Krishna"),
    ("Redwood Retail Tech", "Delhi", "Retail platforms", "Ishaan Gupta"),
    ("Silverline Media", "Kochi", "Media production", "Meera Menon"),
    ("Trident Biotech", "Bhopal", "Life sciences", "Nikhil Verma"),
]


def _slug(name):
    return SLUG_PREFIX + "-".join(name.lower().split())


class Command(BaseCommand):
    help = "Add (or with --remove, delete) 20 demo companies for the visitor booking directory."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true", help="Delete the demo companies and their demo hosts.")

    def handle(self, *args, remove=False, **options):
        if remove:
            self._remove()
        else:
            self._seed()

    @transaction.atomic
    def _seed(self):
        created = 0
        for index, (name, city, tagline, host_name) in enumerate(COMPANIES):
            org, is_new = Organization.objects.get_or_create(
                slug=_slug(name),
                defaults={"name": name, "city": city, "country": "India", "tagline": tagline, "timezone": "Asia/Kolkata"},
            )
            created += is_new

            # Two to six buildings (A1.. in order), each with one to five floors.
            for b_index, b_name in enumerate(BUILDING_NAMES[: 2 + index % 5]):
                building, _ = Building.objects.get_or_create(
                    organization=org, name=b_name, defaults={"floors": 1 + (index + b_index) % 5}
                )
                sync_floors(building)

            dept, _ = Department.objects.get_or_create(organization=org, name="Front office", defaults={"code": "FO"})
            email = f"frontdesk.{org.slug.removeprefix(SLUG_PREFIX)}@{EMAIL_DOMAIN}"
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                user = User.objects.create_user(
                    email=email, password=None, full_name=host_name, role=Role.RECEPTIONIST, organization=org
                )
            if not Employee.objects.filter(user=user).exists():
                Employee.objects.create(
                    user=user,
                    organization=org,
                    employee_id=f"EMP-{org.pk:04d}-{user.pk}",
                    department=dept,
                    building=org.buildings.order_by("name").first(),
                    designation="Front office",
                )
            self.stdout.write(f"{org.slug}: {org.buildings.count()} building(s), host {host_name}")
        self.stdout.write(self.style.SUCCESS(f"Done. {created} new demo compan{'y' if created == 1 else 'ies'}, {len(COMPANIES)} in total."))

    @transaction.atomic
    def _remove(self):
        users = User.objects.filter(email__iendswith=f"@{EMAIL_DOMAIN}")
        orgs = Organization.objects.filter(slug__startswith=SLUG_PREFIX)
        n_users, n_orgs = users.count(), orgs.count()
        orgs.delete()
        users.delete()
        self.stdout.write(self.style.SUCCESS(f"Removed {n_orgs} demo compan{'y' if n_orgs == 1 else 'ies'} and {n_users} demo host(s)."))

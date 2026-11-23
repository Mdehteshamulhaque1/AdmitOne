"""Add sample hosts (Incharge, HR, Trainers, Counsellor, Placement) to a workspace.

    python manage.py seed_sample_staff pyspiders           # add (safe to re-run)
    python manage.py seed_sample_staff pyspiders --remove  # remove them again

Each sample person is a staff member with a designation and a department, so
visitors can pick them under "Person you're meeting" and filter by department.
They have an unusable password and an ``@<slug>-staff.test`` address, so nobody
can sign in as them until an admin sets a real email and password under Team.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Role, User
from organizations.models import AuditLog, Department, Employee, Organization

DEPARTMENTS = [("Administration", "ADM"), ("HR", "HR"), ("Training", "TRN"), ("Counselling", "CNS"), ("Placements", "PLC")]

PEOPLE = [
    ("Rajesh Kumar", "Centre Incharge", "Administration"),
    ("Neha Sharma", "HR Manager", "HR"),
    ("Amit Verma", "Python Trainer", "Training"),
    ("Sana Khan", "Data Science Trainer", "Training"),
    ("Pooja Mishra", "Student Counsellor", "Counselling"),
    ("Vikram Singh", "Placement Officer", "Placements"),
]


def _domain(org):
    return f"{org.slug}-staff.test"


class Command(BaseCommand):
    help = "Add (or --remove) sample hosts with designations and departments for a workspace."

    def add_arguments(self, parser):
        parser.add_argument("org_slug")
        parser.add_argument("--remove", action="store_true")

    def handle(self, org_slug, remove=False, **options):
        org = Organization.objects.filter(slug=org_slug).first()
        if org is None:
            raise CommandError(f"No workspace with slug {org_slug!r}.")
        if remove:
            self._remove(org)
        else:
            self._seed(org)

    @transaction.atomic
    def _seed(self, org):
        depts = {}
        for name, code in DEPARTMENTS:
            dept = Department.objects.filter(organization=org, name__iexact=name).first()
            if dept is None:
                code_taken = Department.objects.filter(organization=org, code=code).exists()
                dept = Department.objects.create(organization=org, name=name, code="" if code_taken else code)
            depts[name] = dept
        added = 0
        for full_name, designation, dept_name in PEOPLE:
            email = f"{full_name.lower().replace(' ', '.')}@{_domain(org)}"
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                user = User.objects.create_user(email=email, password=None, full_name=full_name, role=Role.RECEPTIONIST, organization=org)
                added += 1
            if not Employee.objects.filter(user=user).exists():
                Employee.objects.create(
                    user=user, organization=org, employee_id=f"EMP-{org.pk:04d}-{user.pk}",
                    department=depts[dept_name], designation=designation,
                )
            self.stdout.write(f"{full_name}: {designation} ({dept_name})")
        if added:
            AuditLog.log(None, "Sample staff added", "Organization", org.pk, f"{added} sample hosts", organization_id=org.pk)
        self.stdout.write(self.style.SUCCESS(f"Done. {added} new sample staff in {org.name}."))

    @transaction.atomic
    def _remove(self, org):
        users = User.objects.filter(organization=org, email__iendswith=f"@{_domain(org)}")
        n = users.count()
        users.delete()
        self.stdout.write(self.style.SUCCESS(f"Removed {n} sample staff from {org.name}. Departments were kept."))

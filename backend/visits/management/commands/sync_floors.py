"""Create ``Floor`` rows for every building whose floor count has none.

Buildings created before rooms existed have a ``floors`` count but no
``Floor`` rows, so the visitor booking form cannot offer a floor dropdown
and rooms cannot be placed. The API keeps the two in sync whenever a
building is saved; this command does the same for existing data in one go:

    python manage.py sync_floors
"""

from django.core.management.base import BaseCommand

from organizations.models import Building


class Command(BaseCommand):
    help = "Create missing Floor rows to match each building's floor count."

    def handle(self, *args, **options):
        from api.management_views import sync_floors

        touched = 0
        for building in Building.objects.select_related("organization").order_by("organization__slug", "name"):
            before = building.floor_set.count()
            sync_floors(building)
            after = building.floor_set.count()
            if after != before:
                touched += 1
            self.stdout.write(
                f"{building.organization.slug} / {building.name}: {building.floors} floor(s), "
                f"{before} -> {after} rows"
            )
        self.stdout.write(self.style.SUCCESS(f"Done. {touched} building(s) updated."))

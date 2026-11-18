"""Attribute every legacy Visitor row to exactly one organization.

Runs after ``0010`` added the nullable ``Visitor.organization`` column and
before ``uniq_visitor_org_phone`` is created, so the constraint can only be
added once the data satisfies it.

Step 1 -- attribute / split (``_split_legacy_visitors``)

* one organization in the row's visit history -> adopt that organization;
* several organizations -> keep the row for the lowest organization id and
  clone the PII into one new row per other organization, re-pointing that
  organization's visits and portal sessions at the clone.  Nothing is deleted
  and no tenant is left holding a visit whose visitor belongs to somebody else;
* no visits at all -> left NULL and quarantined: invisible to every tenant,
  and no tenant can silently adopt it either.

Step 2 -- merge duplicate identities (``_merge_duplicate_identities``)

Rows that duplicated on ``(organization, phone)`` are possible while the
visitor had no tenant key.  They are merged into one row per tenant, keeping
the row with the most populated identity fields and backfilling its blanks
from the rows it absorbs, so no PII is discarded.  ``Visit``, ``Blacklist`` and
``VisitorPortalSession`` rows are re-pointed before any delete.

Blacklist entries hang off a person rather than off a visit, so when a row is
split the ban is copied to every clone instead of being kept on a single
tenant -- a duplicated ban is recoverable, a lost one is not.

This migration is forward-only: the clone rows cannot be re-merged without
re-reading the PII they carry, so ``backwards`` is a no-op.
"""

from django.db import migrations, models


def _identity_fields(visitor_model):
    """Editable, non-PK columns copied when a visitor row is split."""
    return [
        f.attname
        for f in visitor_model._meta.concrete_fields
        if f.editable and not f.primary_key and f.name != "organization"
    ]


def _populated(visitor, fields):
    return sum(1 for name in fields if getattr(visitor, name) not in ("", None))


def _split_legacy_visitors(apps, schema_editor):
    Visitor = apps.get_model("visits", "Visitor")
    Visit = apps.get_model("visits", "Visit")
    Blacklist = apps.get_model("visits", "Blacklist")
    PortalSession = apps.get_model("visits", "VisitorPortalSession")

    fields = _identity_fields(Visitor)
    legacy = Visitor.objects.filter(organization_id__isnull=True).order_by("id")

    for visitor in legacy.iterator(chunk_size=500):
        org_ids = sorted(
            set(
                Visit.objects.filter(visitor_id=visitor.pk).values_list(
                    "organization_id", flat=True
                )
            )
        )
        if not org_ids:
            # Nothing to attribute it to: stay NULL and quarantined.
            continue
        visitor.organization_id = org_ids[0]
        visitor.save(update_fields=["organization"])

        for org_id in org_ids[1:]:
            clone = Visitor.objects.create(
                organization_id=org_id,
                **{name: getattr(visitor, name) for name in fields},
            )
            Visit.objects.filter(
                visitor_id=visitor.pk, organization_id=org_id
            ).update(visitor_id=clone.pk)
            PortalSession.objects.filter(
                visitor_id=visitor.pk, organization_id=org_id
            ).update(visitor_id=clone.pk)
            for entry in Blacklist.objects.filter(visitor_id=visitor.pk):
                entry.pk = None
                entry.id = None
                entry.visitor_id = clone.pk
                entry.save()


def _merge_duplicate_identities(apps, schema_editor):
    Visitor = apps.get_model("visits", "Visitor")
    Visit = apps.get_model("visits", "Visit")
    Blacklist = apps.get_model("visits", "Blacklist")
    PortalSession = apps.get_model("visits", "VisitorPortalSession")

    fields = _identity_fields(Visitor)
    duplicate_groups = (
        Visitor.objects.filter(organization__isnull=False)
        .exclude(phone="")
        .values("organization_id", "phone")
        .order_by()
        .annotate(total=models.Count("id"))
        .filter(total__gt=1)
    )

    for group in duplicate_groups.iterator(chunk_size=500):
        rows = list(
            Visitor.objects.filter(
                organization_id=group["organization_id"], phone=group["phone"]
            ).order_by("id")
        )
        canonical = sorted(rows, key=lambda v: (-_populated(v, fields), v.pk))[0]

        for duplicate in rows:
            if duplicate.pk == canonical.pk:
                continue
            Visit.objects.filter(visitor_id=duplicate.pk).update(
                visitor_id=canonical.pk
            )
            Blacklist.objects.filter(visitor_id=duplicate.pk).update(
                visitor_id=canonical.pk
            )
            PortalSession.objects.filter(visitor_id=duplicate.pk).update(
                visitor_id=canonical.pk
            )
            backfilled = False
            for name in fields:
                value = getattr(duplicate, name)
                if value not in ("", None) and not getattr(canonical, name):
                    setattr(canonical, name, value)
                    backfilled = True
            if backfilled:
                canonical.save(update_fields=fields)
            duplicate.delete()


def forwards(apps, schema_editor):
    _split_legacy_visitors(apps, schema_editor)
    _merge_duplicate_identities(apps, schema_editor)


class Migration(migrations.Migration):

    # Not atomic, deliberately.
    #
    # The AddConstraint below emits CREATE UNIQUE INDEX, and PostgreSQL refuses
    # to build an index on a table that still has pending trigger events left
    # over from row writes earlier in the *same* transaction:
    #
    #     cannot CREATE INDEX "visits_visitor" because it has pending
    #     trigger events
    #
    # Django runs a whole migration inside one transaction by default, so the
    # forwards() above -- which inserts clone rows, re-points Visit/Blacklist/
    # VisitorPortalSession rows and merges duplicates -- leaves exactly those
    # events pending when AddConstraint runs.
    #
    # This is a production failure, not just a test one. It is invisible on an
    # empty database because forwards() then touches nothing and there is
    # nothing pending, so `migrate` succeeds on a fresh install and fails on
    # the only databases that actually needed the backfill -- the ones holding
    # legacy visitor rows. Render runs `preDeployCommand: migrate` against
    # Supabase PostgreSQL, so this would have failed the first deploy against
    # real data, after the rewrite was already committed.
    #
    # atomic = False lets forwards() commit before the index is built. The
    # trade-off is that a failure in AddConstraint leaves the data migration
    # applied, which is recoverable (the operation is idempotent by construction
    # and the constraint can be added again); the alternative is a migration
    # that cannot run against the data it exists for.
    atomic = False

    dependencies = [
        ("visits", "0010_visitor_organization"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="visitor",
            constraint=models.UniqueConstraint(
                condition=models.Q(("organization__isnull", False))
                & models.Q(("phone", ""), _negated=True),
                fields=("organization", "phone"),
                name="uniq_visitor_org_phone",
            ),
        ),
    ]

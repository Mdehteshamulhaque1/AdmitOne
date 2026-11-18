"""Give the audit trail an explicit tenant key, and widen entity_id.

Two changes:

* ``AuditLog.organization`` -- several audited actions have no human actor
  (public booking, visitor portal, reminder jobs, the nightly archive), so the
  tenant could not be derived from ``user``.  Deriving it from the actor also
  meant the console filtered ``user__organization=<caller's org>``, which lost
  every system row and, for a caller with no workspace, compiled to ``IS NULL``
  and returned every unassigned actor's entries.

* ``AuditLog.entity_id`` widened 40 -> 64.  The column already stored a UUID
  (``Visit.visit_id``, 36 chars) and was being handed ``Employee.employee_id``
  (up to 50) and ``User.email`` (up to 254), so two existing call sites could
  overflow the column on a strict backend.

The backfill is deliberately conservative: it attributes a row only when the
answer is unambiguous, and leaves everything else NULL rather than guessing.
Reverse drops the column, which discards the backfilled attribution.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_organization(apps, schema_editor):
    """Attribute existing rows to a tenant where it is provable.

    Two independent sources, in priority order:

    1. the row's own ``entity_type == "Organization"`` value -- the workspace
       that was created or edited.  Resolved against a live Organization, so a
       stale id stays NULL.
    2. the actor's workspace, via ``user.organization_id``.

    A row for a Visit entity is *not* backfilled from the visit: the column is
    textual, the visit may since have been deleted, and a wrong guess would
    place one tenant's audit entry in another tenant's log. Those rows keep
    ``organization = NULL`` until the action happens again.
    """
    AuditLog = apps.get_model("organizations", "AuditLog")
    Organization = apps.get_model("organizations", "Organization")

    db = schema_editor.connection.alias
    live_org_ids = set(Organization.objects.using(db).values_list("pk", flat=True))

    # group the un-attributed rows by the tenant we can prove they belong to
    by_org = {}
    rows = (
        AuditLog.objects.using(db)
        .filter(organization__isnull=True)
        .values_list("pk", "entity_type", "entity_id", "user__organization_id")
        .iterator()
    )
    for pk, entity_type, entity_id, actor_org in rows:
        org_id = None

        # 1. the row describes an Organization entity and that id is live
        if entity_type == "Organization" and str(entity_id or "").isdigit():
            candidate = int(entity_id)
            if candidate in live_org_ids:
                org_id = candidate

        # 2. otherwise fall back to the actor's workspace
        if org_id is None and actor_org is not None:
            org_id = actor_org

        if org_id is not None:
            by_org.setdefault(org_id, []).append(pk)

    # one UPDATE per tenant rather than one per row
    for org_id, pks in by_org.items():
        AuditLog.objects.using(db).filter(pk__in=pks).update(organization_id=org_id)


def noop_reverse(apps, schema_editor):
    """Nothing to undo: dropping the column discards the attribution."""


class Migration(migrations.Migration):

    dependencies = [
        ("organizations", "0003_organization_weekly_working_hours"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        # The backfill reads ``User.organization_id`` through the historical
        # model, so it must run after the accounts migrations that shaped the
        # user table; the swappable dependency alone only guarantees 0001.
        ("accounts", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditlog",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Tenant the action belongs to. NULL for a platform-level "
                    "action, or for a row written before this column existed "
                    "whose tenant cannot be determined without guessing."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="audit_logs",
                to="organizations.organization",
            ),
        ),
        migrations.AlterField(
            model_name="auditlog",
            name="entity_id",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(
                fields=["organization", "-created_at"], name="audit_org_created_idx"
            ),
        ),
        migrations.RunPython(backfill_organization, noop_reverse),
    ]

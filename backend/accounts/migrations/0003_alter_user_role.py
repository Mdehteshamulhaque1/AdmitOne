"""Map the legacy six-role RBAC onto the current three-role model.

Before this migration ``accounts.User.role`` accepted six values (see
``accounts/migrations/0001_initial.py``).  The permission sets the old
``accounts/permissions.py`` gave them were:

    SUPER_ADMIN   everything ORG_ADMIN had, plus manage_org, manage_roles, view_all
    ORG_ADMIN     manage_buildings/departments/employees/users, view_audit_logs,
                  blacklist_visitor, badge_print, approve_visitor,
                  checkin_visitor, checkout_visitor, view_reports
    RECEPTIONIST  create_visitor, badge_print, view_reports
    SECURITY      scan_qr, checkin_visitor, checkout_visitor, view_reports
    EMPLOYEE      create_visitor, approve_visitor
    AUDITOR       view_reports, view_audit_logs

The three-role model dropped ``manage_roles`` and ``view_all`` outright -- they
appear nowhere in the current codebase -- so those two names no longer express
any right.  The previous data step mapped *every* legacy value to ``ADMIN``,
which handed the full permission set (``manage_users``, ``manage_org``,
``scan_qr``, ``view_audit_logs``) to all of them, including accounts that were
created with the old field default ``EMPLOYEE`` and had never been granted
anything beyond registering a visitor.

``LEGACY_ROLE_MAP`` maps each legacy value to the narrowest role that still
covers what that role could actually do:

    SUPER_ADMIN -> ADMIN        exact: ADMIN plus the two dropped names
    ORG_ADMIN   -> ADMIN        every ORG_ADMIN right is an ADMIN right
    EMPLOYEE    -> RECEPTIONIST keeps create_visitor, drops approve_visitor
    AUDITOR     -> RECEPTIONIST the model has no read-only role left; of the
                                 three this is the least able to act, and a
                                 visit it registers stays PENDING

``is_superuser`` is not touched and still short-circuits ``user_permissions()``,
so genuine super administrators keep the full permission set no matter what
their role column says.

The migration guarantees:

* **deterministic** - a fixed literal map whose source and target values are
  disjoint, so the order its entries are applied in cannot change the result;
* **idempotent** - each step only selects rows still holding its own legacy
  value, so a second run updates zero rows;
* **non-destructive** - it rewrites the ``role`` column and nothing else.  No
  user row, password, lockout counter or organization assignment is dropped,
  and an unrecognised role value is left as-is rather than promoted.

``backwards`` is deliberately a no-op.  Once a row reads ``ADMIN`` there is no
way to tell which of SUPER_ADMIN / ORG_ADMIN / ADMIN it used to be, and a
reverse that guessed would re-introduce the escalation this migration removes.

For a database that already ran the old version of this step the original
values are unrecoverable, so the affected accounts have to be reviewed by hand
before the first production deploy.
"""

from django.db import migrations, models

#: legacy role value -> current role value (see the module docstring).
LEGACY_ROLE_MAP = {
    "SUPER_ADMIN": "ADMIN",
    "ORG_ADMIN": "ADMIN",
    "EMPLOYEE": "RECEPTIONIST",
    "AUDITOR": "RECEPTIONIST",
}


def map_legacy_roles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    alias = schema_editor.connection.alias
    for legacy_role, new_role in LEGACY_ROLE_MAP.items():
        User.objects.using(alias).filter(role=legacy_role).update(role=new_role)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_initial"),
    ]

    operations = [
        migrations.RunPython(map_legacy_roles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(choices=[("ADMIN", "Admin"), ("RECEPTIONIST", "Receptionist"), ("SECURITY", "Security")], default="ADMIN", max_length=20),
        ),
    ]

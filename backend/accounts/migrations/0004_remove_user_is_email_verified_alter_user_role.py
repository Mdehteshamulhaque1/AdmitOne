"""Least-privilege role default; drop the decorative e-mail-verification flag.

Two changes, both about what the schema *defaults* to rather than about any
particular row.

1. ``User.role`` default: ``ADMIN`` -> ``RECEPTIONIST``.

   The old default meant that any code path constructing a ``User`` without
   naming a role produced an administrator. The public signup endpoint
   (``POST /api/auth/register/``) is exactly such a path, so an anonymous
   request could create an ADMIN, exchange it for a JWT and sign into the
   operations console. A field default is the last line of defence when an
   argument is forgotten, so it now grants the weakest role in the model.

   **Existing rows are deliberately not demoted.** ``AlterField`` rewrites the
   column default only; it does not touch stored values. That is the correct
   scope here: the escalation vector is *new* accounts created without a role.
   Accounts holding ADMIN were provisioned deliberately -- by ``/onboarding``,
   which attaches the caller to a workspace they created, or by an operator in
   the Django admin -- and silently demoting them would break live workspaces.
   If a deployment did expose the anonymous-registration path before this
   migration, the rows it created are still recoverable, because such accounts
   have ``organization IS NULL``: see ``organizations.migrations.0004`` and the
   ``is_active``/``organization`` pair, which identify them exactly. Review and
   deactivate those rows once, by hand.

   Reversing this restores the ``ADMIN`` default, which reintroduces the
   vulnerability. Treat the reverse as a debugging step only.

2. ``User.is_email_verified`` removed.

   Nothing ever read it. Registration set it to ``True`` immediately after
   creating the user, and no authentication path consulted it, so it was not a
   control -- it was a field labelled "verified" that nothing verified. Sitting
   in the admin beside the genuine lockout counters, it read as an assurance
   the system did not provide. There is no verification flow in this project
   (no token, no endpoint, no expiry), so enforcing it rather than removing it
   would have locked out every real user. The state it appeared to describe is
   instead enforced directly, by ``accounts.permissions.has_tenant``.

   The reverse re-adds the column defaulted to ``False``, so the removed values
   are not recovered. They were constants, so nothing of value is lost.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_alter_user_role"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="is_email_verified",
        ),
        migrations.AlterField(
            model_name="user",
            name="role",
            field=models.CharField(
                choices=[
                    ("ADMIN", "Admin"),
                    ("RECEPTIONIST", "Receptionist"),
                    ("SECURITY", "Security"),
                ],
                default="RECEPTIONIST",
                max_length=20,
            ),
        ),
    ]

"""Make the audit trail immutable at the database level.

PostgreSQL (production): a trigger aborts any DELETE on
``organizations_auditlog`` and any UPDATE that changes a recorded fact. The
two nullable foreign keys (``user_id``, ``organization_id``) may still be set
to NULL by Django's ``SET_NULL`` cascade when an actor or workspace is
removed, so the trail outlives them. Row-level triggers do not fire for
TRUNCATE, so a deliberate, privileged purge remains possible.

SQLite (development/CI): the same UPDATE guard is installed. The DELETE guard
is deliberately *not*: SQLite has no TRUNCATE and Django's test-database
flush deletes row by row, so a delete trigger would make the test suite unable
to reset itself. Deletion protection is therefore a property of the
production database, which is the one that matters.

Reversible: the triggers (and the PostgreSQL function) are dropped.
"""

from django.db import migrations

TABLE = "organizations_auditlog"
FACTS = ("action", "entity_type", "entity_id", "details", "ip_address", "created_at")

PG_UP = [
    f"""
CREATE OR REPLACE FUNCTION securegate_auditlog_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit log rows cannot be deleted';
    END IF;
    IF ({", ".join("NEW." + f for f in FACTS)}) IS DISTINCT FROM ({", ".join("OLD." + f for f in FACTS)}) THEN
        RAISE EXCEPTION 'audit log rows cannot be modified';
    END IF;
    IF NEW.user_id IS NOT NULL AND NEW.user_id IS DISTINCT FROM OLD.user_id THEN
        RAISE EXCEPTION 'audit log actor cannot be reassigned';
    END IF;
    IF NEW.organization_id IS NOT NULL AND NEW.organization_id IS DISTINCT FROM OLD.organization_id THEN
        RAISE EXCEPTION 'audit log tenant cannot be reassigned';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
""",
    f"DROP TRIGGER IF EXISTS securegate_auditlog_immutable ON {TABLE}",
    f"""
CREATE TRIGGER securegate_auditlog_immutable
    BEFORE UPDATE OR DELETE ON {TABLE}
    FOR EACH ROW EXECUTE FUNCTION securegate_auditlog_guard()
""",
]
PG_DOWN = [
    f"DROP TRIGGER IF EXISTS securegate_auditlog_immutable ON {TABLE}",
    "DROP FUNCTION IF EXISTS securegate_auditlog_guard()",
]

_SQLITE_CHANGED = " OR ".join(f"NEW.{f} IS NOT OLD.{f}" for f in FACTS)
SQLITE_UP = [
    f"""
CREATE TRIGGER IF NOT EXISTS securegate_auditlog_no_update
    BEFORE UPDATE ON {TABLE}
    WHEN ({_SQLITE_CHANGED})
      OR (NEW.user_id IS NOT NULL AND NEW.user_id IS NOT OLD.user_id)
      OR (NEW.organization_id IS NOT NULL AND NEW.organization_id IS NOT OLD.organization_id)
BEGIN
    SELECT RAISE(ABORT, 'audit log rows cannot be modified');
END
""",
]
SQLITE_DOWN = ["DROP TRIGGER IF EXISTS securegate_auditlog_no_update"]


def _run(statements_by_vendor):
    def apply(apps, schema_editor):
        statements = statements_by_vendor.get(schema_editor.connection.vendor, [])
        with schema_editor.connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement.strip())

    return apply


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0005_audit_hardening"),
    ]

    operations = [
        migrations.RunPython(
            _run({"postgresql": PG_UP, "sqlite": SQLITE_UP}),
            _run({"postgresql": PG_DOWN, "sqlite": SQLITE_DOWN}),
        ),
    ]

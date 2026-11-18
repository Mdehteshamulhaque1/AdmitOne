"""Helpers for tests that run migrations back and forth.

``MigrationExecutor.migrate`` treats its argument as the **complete** desired
database state: any app missing from it is unapplied all the way back to zero.
Handing it a single ``[("visits", "0009_...")]`` therefore also unapplies
``accounts``, ``organizations`` and everything else, even when the test only
meant to rewind one app.

That is slow and misleading -- the test silently depends on other apps being
rebuilt -- and on PostgreSQL it fails outright. Rebuilding an app inside one
transaction runs its data migrations together with its DDL, and a data
migration that writes rows leaves pending trigger events, so a later
``CREATE INDEX`` in the same transaction is refused::

    cannot CREATE INDEX "visits_visitor" because it has pending trigger events

Both symptoms trace back to the same mistake: tests that were green only
because SQLite tolerates the rewind, and that fail the moment the suite runs on
the database production actually uses. The fix belongs here rather than at each
call site so the invariant is stated once.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def expand_targets(targets):
    """Return a *complete* migration target list.

    ``targets`` names the apps a test wants to pin, and may be given either as a
    bare ``("visits", "0009_...")`` pair or as an iterable of such pairs. Every
    app not named is left at its latest leaf, so rewinding one app leaves the
    rest of the schema alone.

    An empty ``targets`` means "latest", which is the correct value for the
    cleanup half of a migration test.
    """
    if targets and isinstance(targets[0], str):
        targets = [tuple(targets)]

    pinned = {app_label: migration for app_label, migration in targets}

    executor = MigrationExecutor(connection)
    executor.loader.build_graph()

    complete = [
        node for node in executor.loader.graph.leaf_nodes() if node[0] not in pinned
    ]
    complete.extend(pinned.items())
    return complete


def leaf_targets():
    """Every app at its latest migration."""
    return expand_targets([])
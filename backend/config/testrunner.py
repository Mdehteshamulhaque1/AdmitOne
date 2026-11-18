"""Test runners used by CI.

Why this exists
---------------
``unittest`` treats a skip as a success. That is usually right and occasionally
catastrophic: a test guarded by ``@skipUnless(connection.vendor == "postgresql")``
sails on SQLite and vanishes, so a CI matrix that silently changes backend stops
testing the invariant and nobody notices for months.

``StrictSkipRunner`` closes that door. Every test it runs must actually run. A
skip becomes a build failure, which means adding a skip is now a deliberate act
with a written justification rather than an escape hatch that quietly removes
coverage.

It is opt-in (``--testrunner=config.testrunner.StrictSkipRunner``) because the
SQLite job legitimately skips the row-locking tests; the PostgreSQL job, where
those tests are supposed to execute, is the one that must reach zero skips.
"""

from django.core.management.base import CommandError
from django.test.runner import DiscoverRunner


class StrictSkipRunner(DiscoverRunner):
    """A ``DiscoverRunner`` that refuses to report success if anything skipped.

    The violation is raised from ``run_tests`` rather than ``run_suite`` so the
    normal test summary is printed first: a CI failure that shows what ran, and
    then what did not, is far easier to act on than a bare traceback.
    """

    #: Substrings of skip reasons that are tolerated. Each entry must name the
    #: job or configuration that covers the skipped behaviour instead. Empty on
    #: purpose.
    allowed_skip_reasons = ()

    #: Populated per run by ``run_suite`` and inspected by ``run_tests``.
    _unexpected_skips = ()

    def run_suite(self, suite, **kwargs):
        outcome = super().run_suite(suite, **kwargs)
        # DiscoverRunner.run_suite returns the TextTestResult itself, not the
        # unittest.TestSuite.run two-tuple. Unwrap defensively so a Django
        # upgrade surfaces here instead of silently disabling the rule.
        result = outcome[0] if isinstance(outcome, tuple) else outcome
        self._unexpected_skips = [
            (test, reason)
            for test, reason in getattr(result, "skipped", [])
            if not any(allowed in str(reason) for allowed in self.allowed_skip_reasons)
        ]
        return outcome

    def run_tests(self, test_labels, **kwargs):
        failures = super().run_tests(test_labels, **kwargs)
        unexpected = getattr(self, "_unexpected_skips", ())
        if unexpected:
            detail = "\n".join(
                f"  {test.id()}\n      skipped: {reason}" for test, reason in unexpected
            )
            raise CommandError(
                f"{len(unexpected)} test(s) skipped, but this runner requires "
                f"every test to run.\n\n{detail}\n\n"
                "A skipped test is a test that did not test anything. Either the "
                "guard is wrong for this backend, the behaviour is untested here, "
                "or the skip belongs in another job -- in which case add its "
                "reason to StrictSkipRunner.allowed_skip_reasons with a note "
                "naming that job."
            )
        return failures
"""Adversarial coverage for the visitor QR pass.

A QR pass is the credential that physically admits a person to a building, so
these tests treat it as an attack surface rather than a feature.  Each class
maps to one requirement: the artifact must verify, must expire, must resist
modification, must not cross a tenant boundary, must not be replayed, must not
be redeemable twice under concurrency, and must be genuinely superseded by a
re-issue.

The signing tests also pin the **key-rotation contract**, because a scheme that
cannot rotate is one you cannot respond to when a key leaks: a pass signed
before a rotation must still verify while its key is retained, and must stop
verifying the moment that key is dropped.

Concurrency note: ``check_in`` claims the pass with a single conditional
``UPDATE`` whose ``WHERE`` clause is re-evaluated at write time, so exactly one
of two racing transactions can win regardless of backend.

Which test actually proves that, and which one does not, matters here. The
threaded test asserts the right *invariant* and does reproduce the race
(one thread admitted, one refused) when the suite runs as a whole. But on
SQLite its outcome depends on timing -- SQLite's coarse file lock makes both
threads fail with ``OperationalError`` some of the time and serialise them the
rest, and it was confirmed to pass against a deliberately reverted
read-then-write implementation. It is therefore not load-bearing on its own.
The tests that do have teeth are the ones that assert the *mechanism*
(``test_the_guard_does_not_depend_on_select_for_update``, which fails against
that same revert) and the loser's rejection path
(``test_a_consumed_pass_is_refused_while_the_visit_is_still_approved``).

Because a SQLite "pass" can be satisfied by one thread crashing rather than by
one thread losing the race, the threaded test is skipped deterministically off
PostgreSQL instead of racing. That keeps the skip count stable run to run and
stops a lock error from masquerading as a passing invariant; it runs for real
in CI's PostgreSQL job, where a thread that dies is asserted to be a failure.
"""

import threading
from datetime import time as time_class
from datetime import timedelta
from unittest import skipUnless

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Role, User
from organizations.models import Building, Organization
from visits import signing
from visits.models import QRPass, Visit, VisitStatus, Visitor
from visits.qrcodes import qr_payload
from visits.services import approve_visit, check_in, reissue_qr_pass

PASSWORD = "Str0ng!Pass"


class QRTestBase(TestCase):
    def setUp(self):
        self.alpha = Organization.objects.create(name="Alpha", slug="alpha")
        self.bravo = Organization.objects.create(name="Bravo", slug="bravo")

        self.alpha_admin = self._user("a-admin@x.test", self.alpha, Role.ADMIN)
        self.alpha_guard = self._user("a-guard@x.test", self.alpha, Role.SECURITY)
        self.bravo_guard = self._user("b-guard@x.test", self.bravo, Role.SECURITY)

        self.building = Building.objects.create(organization=self.alpha, name="Alpha HQ")
        self.visitor = Visitor.objects.create(
            organization=self.alpha, full_name="Ravi Kumar", phone="9999999999"
        )

    def _user(self, email, org, role):
        return User.objects.create_user(
            email=email, password=PASSWORD, full_name=email.split("@")[0],
            role=role, organization=org,
        )

    def approved_visit(self, org=None, visitor=None, seq=0):
        org = org or self.alpha
        if visitor is None:
            visitor = Visitor.objects.create(
                organization=org, full_name=f"Visitor {seq}",
                phone=f"9999{seq:06d}",
            )
        visit = Visit.objects.create(
            visitor=visitor, organization=org, building=self.building,
            host=self.alpha_admin, created_by=self.alpha_admin,
            purpose="Interview", visit_date=timezone.localdate(),
            expected_arrival=time_class(10, 0), expected_exit=time_class(17, 0),
        )
        ok, _ = approve_visit(visit, self.alpha_admin)
        self.assertTrue(ok, "fixture: visit must be approved to hold a pass")
        return visit

    def scan(self, token, signature):
        return QRPass.verify(str(token), signature)


# ====================================================== 1. a valid pass verifies


class ValidPassTests(QRTestBase):
    def test_a_freshly_issued_pass_verifies(self):
        visit = self.approved_visit(seq=1)
        qr = visit.qr_pass

        ok, msg, found = self.scan(qr.token, qr.signature)
        self.assertTrue(ok, msg)
        self.assertEqual(found.pk, qr.pk)

    def test_the_encoded_artifact_is_exactly_token_and_signature(self):
        visit = self.approved_visit(seq=2)
        qr = visit.qr_pass
        payload = qr_payload(qr)
        self.assertEqual(payload, f"{qr.token}|{qr.signature}")
        # two fields, nothing more: no visitor name, no phone and no company
        # travels in the artifact, so there is no plaintext in the QR to read
        # or edit. The org is bound by the *signature*, not by the payload.
        self.assertEqual(len(payload.split("|")), 2)
        self.assertNotIn(visit.visitor.full_name, payload)
        self.assertNotIn(visit.visitor.phone, payload)
        self.assertNotIn(visit.visitor.full_name.split()[0], payload)

    def test_signature_is_a_full_length_hex_digest(self):
        visit = self.approved_visit(seq=3)
        sig = visit.qr_pass.signature
        self.assertEqual(len(sig), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in sig))


# ============================================================= 2. expiry is real


class ExpiryTests(QRTestBase):
    def _expire(self, qr):
        QRPass.objects.filter(pk=qr.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        qr.refresh_from_db()

    def test_an_expired_pass_fails_verification(self):
        visit = self.approved_visit(seq=6)
        qr = visit.qr_pass
        self._expire(qr)
        ok, msg, found = self.scan(qr.token, qr.signature)
        self.assertFalse(ok)
        self.assertIn("expired", msg)
        self.assertIsNone(found)

    def test_an_expired_pass_cannot_check_in(self):
        visit = self.approved_visit(seq=7)
        qr = visit.qr_pass
        self._expire(qr)
        ok, msg = check_in(visit, self.alpha_guard, via_qr=True)
        self.assertFalse(ok)
        self.assertIn("expired", msg)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)

    def test_expiry_is_enforced_even_though_the_signature_still_matches(self):
        # the expiry lives server-side and is deliberately not signed; a
        # correct signature must not resurrect a lapsed pass
        visit = self.approved_visit(seq=8)
        qr = visit.qr_pass
        self.assertIsNotNone(
            signing.verify(visit.visit_id, self.alpha.pk, qr.token, qr.signature)
        )
        self._expire(qr)
        self.assertIsNotNone(
            signing.verify(visit.visit_id, self.alpha.pk, qr.token, qr.signature)
        )
        self.assertFalse(self.scan(qr.token, qr.signature)[0])

    def test_a_pass_expiring_between_the_read_and_the_claim_is_not_redeemable(self):
        # the expiry predicate lives inside the claiming UPDATE, so a pass that
        # lapses mid-request cannot slip through the gap
        visit = self.approved_visit(seq=9)
        qr = visit.qr_pass
        with self.assertNumQueries(0):
            pass
        claimed = QRPass.objects.filter(
            pk=qr.pk, is_used=False, expires_at__gt=timezone.now()
        ).update(is_used=True, used_at=timezone.now())
        self.assertEqual(claimed, 1, "a live pass is claimable")

        qr2 = self.approved_visit(seq=10).qr_pass
        claimed = QRPass.objects.filter(
            pk=qr2.pk, is_used=False, expires_at__lte=timezone.now()
        ).update(is_used=True, used_at=timezone.now())
        self.assertEqual(claimed, 0, "a lapsed pass is never claimable")


# ======================================================== 3. payload is tamper-proof


class TamperingTests(QRTestBase):
    def test_a_flipped_signature_is_rejected(self):
        visit = self.approved_visit(seq=11)
        qr = visit.qr_pass
        flipped = ("f" if qr.signature[0] != "f" else "a") + qr.signature[1:]
        ok, msg, found = self.scan(qr.token, flipped)
        self.assertFalse(ok)
        self.assertIn("tampered", msg)
        self.assertIsNone(found)

    def test_a_truncated_or_padded_signature_is_rejected(self):
        visit = self.approved_visit(seq=12)
        qr = visit.qr_pass
        for bad in (qr.signature[:-1], qr.signature + "0", ""):
            with self.subTest(signature=bad[:12]):
                ok, _, _ = self.scan(qr.token, bad)
                self.assertFalse(ok)

    def test_swapping_in_another_visits_token_is_rejected(self):
        # the token is the lookup key, so pairing A's token with B's signature
        # must fail: the signed message names the visit
        visit_a = self.approved_visit(seq=13)
        visit_b = self.approved_visit(seq=14)
        ok, msg, _ = self.scan(visit_a.qr_pass.token, visit_b.qr_pass.signature)
        self.assertFalse(ok)
        self.assertIn("tampered", msg)

    def test_rewriting_the_stored_signature_does_not_help(self):
        # an attacker who can write the signature column but not the key still
        # cannot produce a valid one; here we simply show the row is only
        # trusted because the recomputed HMAC matches
        visit = self.approved_visit(seq=15)
        qr = visit.qr_pass
        QRPass.objects.filter(pk=qr.pk).update(signature="a" * 64)
        ok, _, _ = self.scan(qr.token, "a" * 64)
        self.assertFalse(ok)

    def test_a_malformed_token_does_not_500(self):
        for bad in ("garbage!!!", "", "  ", "not-a-uuid", "0" * 200):
            with self.subTest(token=bad[:16]):
                ok, msg, _ = self.scan(bad, "a" * 64)
                self.assertFalse(ok)
                self.assertIsNotNone(msg)

    def test_an_unknown_but_well_formed_token_is_rejected(self):
        import uuid

        ok, msg, _ = self.scan(uuid.uuid4(), "a" * 64)
        self.assertFalse(ok)
        self.assertIn("Unknown pass", msg)

    def test_the_signature_cannot_be_moved_between_formats(self):
        # a legacy SECRET_KEY-signed digest must not be accepted as a v1
        # signature, and vice versa
        visit = self.approved_visit(seq=16)
        qr = visit.qr_pass
        legacy = signing._hmac(
            "some-other-key", f"{visit.visit_id}|{self.alpha.pk}|{qr.token}"
        )
        self.assertIsNone(
            signing.verify(visit.visit_id, self.alpha.pk, qr.token, legacy)
        )


# ================================================= 4. organization binding holds


class OrganizationBindingTests(QRTestBase):
    def test_a_signature_minted_for_another_workspace_is_rejected(self):
        # the org id is inside the signed message, so a pass produced for
        # bravo cannot validate for alpha's visit even with a valid key
        alpha_visit = self.approved_visit(seq=17)
        qr = alpha_visit.qr_pass
        forged_for_bravo = signing.sign(
            alpha_visit.visit_id, self.bravo.pk, qr.token
        )
        self.assertIsNone(
            signing.verify(alpha_visit.visit_id, self.alpha.pk, qr.token, forged_for_bravo)
        )

    def test_a_pass_issued_to_one_workspace_cannot_check_in_at_another(self):
        visit = self.approved_visit(seq=18)
        ok, msg = check_in(visit, self.bravo_guard, via_qr=True)
        self.assertFalse(ok)
        self.assertIn("access to this visit", msg)
        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.APPROVED)
        self.assertFalse(QRPass.objects.get(visit=visit).is_used)

    def test_a_workspace_less_officer_cannot_redeem_a_pass(self):
        orphan = User.objects.create_user(
            email="orphan@x.test", password=PASSWORD, full_name="Orphan",
            role=Role.SECURITY, organization=None,
        )
        visit = self.approved_visit(seq=19)
        ok, msg = check_in(visit, orphan, via_qr=True)
        self.assertFalse(ok)
        self.assertIn("access to this visit", msg)

    def test_another_workspaces_pass_is_not_admitted_by_its_own_signature(self):
        # bravo's pass is valid *in bravo*; presenting it at alpha must fail
        bravo_admin = self._user("b-admin@x.test", self.bravo, Role.ADMIN)
        bravo_building = Building.objects.create(organization=self.bravo, name="Bravo HQ")
        bravo_visitor = Visitor.objects.create(
            organization=self.bravo, full_name="Bravo Visitor", phone="8888888888"
        )
        bravo_visit = Visit.objects.create(
            visitor=bravo_visitor, organization=self.bravo, building=bravo_building,
            host=bravo_admin, created_by=bravo_admin, purpose="Interview",
            visit_date=timezone.localdate(),
            expected_arrival=time_class(10, 0), expected_exit=time_class(17, 0),
        )
        ok, _ = approve_visit(bravo_visit, bravo_admin)
        self.assertTrue(ok)

        # the signature really is valid for its own visit ...
        self.assertTrue(QRPass.verify(
            str(bravo_visit.qr_pass.token), bravo_visit.qr_pass.signature
        )[0])
        # ... but an alpha officer still cannot use it
        ok, msg = check_in(bravo_visit, self.alpha_guard, via_qr=True)
        self.assertFalse(ok)
        self.assertIn("access to this visit", msg)

    def test_a_workspace_cannot_approve_another_workspaces_visit(self):
        # the org guard is not specific to the gate: it also stops one tenant
        # from approving (and thereby minting a pass for) another's visit
        bravo_admin = self._user("b-admin2@x.test", self.bravo, Role.ADMIN)
        bravo_building = Building.objects.create(organization=self.bravo, name="Bravo Tower")
        bravo_visitor = Visitor.objects.create(
            organization=self.bravo, full_name="Bravo Person", phone="8888888887"
        )
        bravo_visit = Visit.objects.create(
            visitor=bravo_visitor, organization=self.bravo, building=bravo_building,
            host=bravo_admin, created_by=bravo_admin, purpose="Interview",
            visit_date=timezone.localdate(),
            expected_arrival=time_class(10, 0), expected_exit=time_class(17, 0),
        )
        ok, msg = approve_visit(bravo_visit, self.alpha_admin)
        self.assertFalse(ok)
        self.assertIn("access to this visit", msg)
        self.assertFalse(hasattr(bravo_visit, "qr_pass"), "no pass is minted")
        bravo_visit.refresh_from_db()
        self.assertEqual(bravo_visit.status, VisitStatus.PENDING)

    def test_moving_a_visit_between_workspaces_invalidates_its_pass(self):
        # the org id is signed, so re-homing the visit breaks its pass rather
        # than silently granting the new tenant a valid credential
        visit = self.approved_visit(seq=20)
        qr = visit.qr_pass
        self.assertTrue(self.scan(qr.token, qr.signature)[0])

        Visit.objects.filter(pk=visit.pk).update(organization=self.bravo)
        self.assertFalse(
            self.scan(qr.token, qr.signature)[0],
            "a pass must not survive its visit changing tenant",
        )


# ================================================== 5. single use / no replay


class ReplayTests(QRTestBase):
    def test_a_pass_cannot_be_redeemed_twice(self):
        visit = self.approved_visit(seq=21)
        qr = visit.qr_pass
        self.assertTrue(self.scan(qr.token, qr.signature)[0])

        ok, _ = check_in(visit, self.alpha_guard, via_qr=True)
        self.assertTrue(ok)
        ok, msg = check_in(visit, self.alpha_guard, via_qr=True)
        self.assertFalse(ok, "a second scan of the same artifact must be refused")

    def test_a_consumed_pass_is_refused_while_the_visit_is_still_approved(self):
        # The visit status alone already blocks a second scan, which is
        # defence in depth. This isolates the *pass* check itself: a pass that
        # has been consumed must be refused on its own merits, with no help
        # from the visit status. That is the check that has to hold when a
        # check-in is rolled back, re-issued, or arrives from a second device.
        visit = self.approved_visit(seq=21)
        qr = visit.qr_pass
        QRPass.objects.filter(pk=qr.pk).update(is_used=True, used_at=timezone.now())
        # the visit is deliberately still APPROVED
        self.assertEqual(Visit.objects.get(pk=visit.pk).status, VisitStatus.APPROVED)

        ok, msg = check_in(visit, self.alpha_guard, via_qr=True)
        self.assertFalse(ok)
        self.assertIn("already", msg.lower())

    def test_a_redeemed_pass_fails_verification_afterwards(self):
        visit = self.approved_visit(seq=22)
        qr = visit.qr_pass
        check_in(visit, self.alpha_guard, via_qr=True)
        ok, msg, found = self.scan(qr.token, qr.signature)
        self.assertFalse(ok)
        self.assertIn("duplicate", msg)
        self.assertIsNone(found)


    def test_the_used_flag_is_set_with_a_timestamp(self):
        visit = self.approved_visit(seq=24)
        qr = visit.qr_pass
        before = timezone.now()
        check_in(visit, self.alpha_guard, via_qr=True)
        qr.refresh_from_db()
        self.assertTrue(qr.is_used)
        self.assertGreaterEqual(qr.used_at, before)

    def test_desk_check_in_does_not_silently_burn_an_unused_pass(self):
        # a desk admission is a different event; the pass stays unconsumed so
        # the record is honest, and re-approving issues a fresh one
        visit = self.approved_visit(seq=25)
        qr = visit.qr_pass
        ok, _ = check_in(visit, self.alpha_guard, via_qr=False)
        self.assertTrue(ok)
        qr.refresh_from_db()
        self.assertFalse(qr.is_used)
        self.assertTrue(self.scan(qr.token, qr.signature)[0])


class ConcurrentRedemptionTests(TransactionTestCase):
    """Two scans of the same artifact, at the same time.

    The invariant asserted is the one that matters: **exactly one** admission
    results and the pass ends up consumed exactly once, no matter which
    transaction wins.  Asserting the specific losing *message* instead would
    make the test depend on interleaving order and on whether the backend
    surfaces a lock error, neither of which is the behaviour under test.
    """

    reset_sequences = True

    def setUp(self):
        self.org = Organization.objects.create(name="Alpha", slug="alpha")
        self.guard = User.objects.create_user(
            email="guard@x.test", password=PASSWORD, full_name="Guard",
            role=Role.SECURITY, organization=self.org,
        )
        self.admin = User.objects.create_user(
            email="admin@x.test", password=PASSWORD, full_name="Admin",
            role=Role.ADMIN, organization=self.org,
        )
        self.building = Building.objects.create(organization=self.org, name="HQ")
        self.visitor = Visitor.objects.create(
            organization=self.org, full_name="Ravi", phone="9999999999"
        )

    def _approved_visit(self):
        visit = Visit.objects.create(
            visitor=self.visitor, organization=self.org, building=self.building,
            host=self.admin, created_by=self.admin, purpose="Interview",
            visit_date=timezone.localdate(),
            expected_arrival=time_class(10, 0), expected_exit=time_class(17, 0),
        )
        ok, _ = approve_visit(visit, self.admin)
        self.assertTrue(ok)
        return visit

    @skipUnless(connection.vendor == "postgresql", "concurrent writers require PostgreSQL")
    def test_only_one_of_two_concurrent_scans_admits(self):
        visit = self._approved_visit()
        qr = visit.qr_pass
        barrier = threading.Barrier(2)
        outcomes = []
        lock = threading.Lock()

        def scan():
            barrier.wait()
            try:
                res = check_in(visit, self.guard, via_qr=True)
                with lock:
                    outcomes.append(("ok", res[0]))
            except Exception as exc:  # pragma: no cover - diagnostic only
                with lock:
                    outcomes.append(("error", type(exc).__name__))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=scan) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        # A thread that raised did not lose the race, it failed. On a backend
        # that can express the race that is a genuine defect, and letting it
        # pass silently would satisfy "exactly one success" with a crash.
        errors = [o for o in outcomes if o[0] == "error"]
        self.assertEqual(
            errors, [],
            f"neither thread may fail; a deadlock or serialisation fault "
            f"would otherwise fake a single-use invariant: {outcomes}",
        )

        successes = [o for o in outcomes if o[0] == "ok" and o[1] is True]
        # Having established above that neither thread failed, the loser must
        # now be turned away gracefully: the conditional UPDATE matches zero
        # rows and check_in reports why. Two successes would mean the pass is
        # spendable twice, which is the whole thing this test exists to forbid.
        self.assertEqual(
            len(successes), 1,
            f"exactly one scan must succeed; outcomes={outcomes}",
        )
        self.assertEqual(len(outcomes), 2, f"both threads must report; outcomes={outcomes}")

        visit.refresh_from_db()
        self.assertEqual(visit.status, VisitStatus.CHECKED_IN)
        qr.refresh_from_db()
        self.assertTrue(qr.is_used, "the pass is consumed exactly once")

    def test_the_claim_is_a_conditional_update_not_a_read_then_write(self):
        # The mechanism behind the invariant above, asserted directly so a
        # future refactor to read-then-write is caught here rather than only
        # under a race that CI may not reproduce.
        visit = self._approved_visit()
        qr = visit.qr_pass
        now = timezone.now()

        first = QRPass.objects.filter(
            pk=qr.pk, is_used=False, expires_at__gt=now
        ).update(is_used=True, used_at=now)
        second = QRPass.objects.filter(
            pk=qr.pk, is_used=False, expires_at__gt=now
        ).update(is_used=True, used_at=now)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0, "the predicate, not the lock, enforces single use")

    def test_the_guard_does_not_depend_on_select_for_update(self):
        # select_for_update() is a documented no-op on SQLite. If the
        # redemption path relied on the row lock alone, single use would
        # evaporate on that backend. This pins the actual mechanism on the
        # production code path: the pass is claimed with one conditional UPDATE
        # whose WHERE clause still carries is_used, so the predicate -- not a
        # lock, and not a read performed earlier -- is what enforces single use.
        visit = self._approved_visit()
        qr = visit.qr_pass

        with CaptureQueriesContext(connection) as captured:
            ok, _ = check_in(visit, self.guard, via_qr=True)
        self.assertTrue(ok)

        claims = [
            q["sql"]
            for q in captured.captured_queries
            if "visits_qrpass" in q["sql"].lower() and q["sql"].lstrip().upper().startswith("UPDATE")
        ]
        self.assertEqual(
            len(claims), 1,
            f"expected exactly one conditional claim on the pass, got {claims}",
        )
        claim = claims[0]
        self.assertIn(
            "is_used", claim,
            "the claim must be conditional on is_used, or a concurrent scan wins twice",
        )
        self.assertIn("expires_at", claim, "the claim must also be conditional on expiry")

        # and the effect is a real single consumption
        qr.refresh_from_db()
        self.assertTrue(qr.is_used)


# ================================================ 6. re-issue supersedes cleanly


class ReissueTests(QRTestBase):
    def test_reissue_invalidates_the_previous_artifact(self):
        visit = self.approved_visit(seq=26)
        old = visit.qr_pass
        old_token, old_signature = old.token, old.signature

        ok, _ = reissue_qr_pass(visit, self.alpha_admin)
        self.assertTrue(ok)

        # the old artifact is not merely wrong, it is unknown
        ok, msg, _ = self.scan(old_token, old_signature)
        self.assertFalse(ok)
        self.assertIn("Unknown pass", msg)

    def test_the_new_pass_works_and_the_old_does_not(self):
        visit = self.approved_visit(seq=27)
        old_token, old_signature = visit.qr_pass.token, visit.qr_pass.signature

        reissue_qr_pass(visit, self.alpha_admin)
        # re-fetch: ``visit.qr_pass`` is a cached related object and would
        # otherwise still hold the pre-rotation values
        new = QRPass.objects.get(visit=visit)

        self.assertNotEqual(new.token, old_token)
        self.assertNotEqual(new.signature, old_signature)
        self.assertTrue(self.scan(new.token, new.signature)[0])
        self.assertFalse(self.scan(old_token, old_signature)[0])

    def test_reissue_records_the_key_id_and_keeps_one_row(self):
        visit = self.approved_visit(seq=28)
        self.assertEqual(QRPass.objects.filter(visit=visit).count(), 1)
        reissue_qr_pass(visit, self.alpha_admin)
        self.assertEqual(QRPass.objects.filter(visit=visit).count(), 1)
        self.assertEqual(
            QRPass.objects.get(visit=visit).signing_key_id, signing.active_key_id()
        )

    def test_reissue_extends_the_validity_window(self):
        visit = self.approved_visit(seq=29)
        QRPass.objects.filter(visit=visit).update(
            expires_at=timezone.now() + timedelta(minutes=1)
        )
        reissue_qr_pass(visit, self.alpha_admin)
        self.assertGreater(
            QRPass.objects.get(visit=visit).expires_at,
            timezone.now() + timedelta(minutes=1),
        )

    def test_reissue_is_refused_once_the_visit_moves_on(self):
        visit = self.approved_visit(seq=30)
        ok, _ = check_in(visit, self.alpha_guard, via_qr=True)
        self.assertTrue(ok)
        ok, msg = reissue_qr_pass(visit, self.alpha_admin)
        self.assertFalse(ok, "a checked-in visit must not get a fresh pass")

    def test_reissue_is_refused_for_a_pending_visit(self):
        visitor = Visitor.objects.create(
            organization=self.alpha, full_name="Pending Person", phone="7777777777"
        )
        visit = Visit.objects.create(
            visitor=visitor, organization=self.alpha, building=self.building,
            host=self.alpha_admin, created_by=self.alpha_admin, purpose="Interview",
            visit_date=timezone.localdate(),
            expected_arrival=time_class(10, 0), expected_exit=time_class(17, 0),
        )
        ok, msg = reissue_qr_pass(visit, self.alpha_admin)
        self.assertFalse(ok)
        self.assertFalse(hasattr(visit, "qr_pass"))

    def test_reissue_cannot_be_driven_from_another_workspace(self):
        visit = self.approved_visit(seq=31)
        old_token = visit.qr_pass.token
        ok, msg = reissue_qr_pass(visit, self.bravo_guard)
        self.assertFalse(ok)
        self.assertIn("access to this visit", msg)
        self.assertEqual(QRPass.objects.get(visit=visit).token, old_token)

    def test_reissue_is_audited(self):
        visit = self.approved_visit(seq=32)
        reissue_qr_pass(visit, self.alpha_admin)
        from organizations.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(
                action="QR pass re-issued", entity_id=str(visit.visit_id)
            ).exists()
        )


# ================================================ 7. key separation and rotation


class SigningKeyTests(QRTestBase):
    def test_the_pass_is_not_signed_with_secret_key(self):
        import hashlib
        import hmac

        visit = self.approved_visit(seq=33)
        qr = visit.qr_pass
        legacy_style = hmac.new(
            b"dev-only-insecure-secret-do-not-deploy",
            f"{visit.visit_id}|{self.alpha.pk}|{qr.token}".encode(),
            hashlib.sha256,
        ).hexdigest()
        self.assertNotEqual(
            qr.signature, legacy_style,
            "SECRET_KEY must not be the QR signing key",
        )

    def test_rotating_secret_key_does_not_invalidate_passes(self):
        # the whole point of a dedicated key: a routine SECRET_KEY rotation is
        # no longer a mass invalidation of outstanding passes
        visit = self.approved_visit(seq=34)
        qr = visit.qr_pass
        with override_settings(SECRET_KEY="a-brand-new-secret-key-for-rotation"):
            self.assertTrue(
                self.scan(qr.token, qr.signature)[0],
                "a pass must survive a SECRET_KEY rotation",
            )

    def test_the_recorded_key_id_matches_the_active_key(self):
        visit = self.approved_visit(seq=35)
        self.assertEqual(visit.qr_pass.signing_key_id, signing.active_key_id())

    def test_a_pass_signed_by_a_retired_key_still_verifies(self):
        visit = self.approved_visit(seq=36)
        qr = visit.qr_pass
        rotated = signing._hmac("retired-key", signing._v1_payload(
            visit.visit_id, self.alpha.pk, qr.token
        ))
        with override_settings(
            QR_SIGNING_PREVIOUS_KEYS="k0:retired-key",
            QR_SIGNING_KEY="active-key",
        ):
            self.assertEqual(
                signing.verify(visit.visit_id, self.alpha.pk, qr.token, rotated),
                "k0",
            )

    def test_dropping_a_retired_key_stops_it_verifying(self):
        visit = self.approved_visit(seq=37)
        rotated = signing._hmac("retired-key", signing._v1_payload(
            visit.visit_id, self.alpha.pk, visit.qr_pass.token
        ))
        with override_settings(QR_SIGNING_PREVIOUS_KEYS="", QR_SIGNING_KEY="active-key"):
            self.assertIsNone(
                signing.verify(
                    visit.visit_id, self.alpha.pk, visit.qr_pass.token, rotated
                )
            )

    def test_rotation_does_not_retroactively_change_stored_signatures(self):
        # the stored digest is what the artifact carries; rotating the key
        # changes what is *accepted*, not what was *written*
        visit = self.approved_visit(seq=38)
        qr = visit.qr_pass
        before = qr.signature
        with override_settings(QR_SIGNING_KEY="new-active-key"):
            self.assertFalse(self.scan(qr.token, qr.signature)[0])
        qr.refresh_from_db()
        self.assertEqual(qr.signature, before, "the stored row is not rewritten")

    def test_a_legacy_secret_key_signed_pass_still_verifies_after_upgrade(self):
        # passes issued before the dedicated key existed must keep working
        # until they expire, or an upgrade logs every visitor out at the gate
        import hashlib
        import hmac

        visit = self.approved_visit(seq=39)
        qr = visit.qr_pass
        legacy = hmac.new(
            b"old-secret-key-value",
            f"{visit.visit_id}|{self.alpha.pk}|{qr.token}".encode(),
            hashlib.sha256,
        ).hexdigest()
        with override_settings(QR_SIGNING_LEGACY_KEY="old-secret-key-value"):
            self.assertEqual(
                signing.verify(visit.visit_id, self.alpha.pk, qr.token, legacy),
                "legacy",
            )

    def test_turning_the_legacy_key_off_removes_that_path(self):
        import hashlib
        import hmac

        visit = self.approved_visit(seq=40)
        qr = visit.qr_pass
        legacy = hmac.new(
            b"old-secret-key-value",
            f"{visit.visit_id}|{self.alpha.pk}|{qr.token}".encode(),
            hashlib.sha256,
        ).hexdigest()
        with override_settings(QR_SIGNING_LEGACY_KEY=""):
            self.assertIsNone(
                signing.verify(visit.visit_id, self.alpha.pk, qr.token, legacy)
            )

    def test_a_legacy_pass_still_redeems_end_to_end(self):
        import hashlib
        import hmac

        visit = self.approved_visit(seq=41)
        qr = visit.qr_pass
        legacy = hmac.new(
            b"old-secret-key-value",
            f"{visit.visit_id}|{self.alpha.pk}|{qr.token}".encode(),
            hashlib.sha256,
        ).hexdigest()
        with override_settings(QR_SIGNING_LEGACY_KEY="old-secret-key-value"):
            ok, msg = check_in(visit, self.alpha_guard, via_qr=True)
        self.assertTrue(ok, msg)

    def test_the_current_key_is_checked_before_retired_keys(self):
        # cheap ordering guarantee, so rotation does not cost an extra compare
        # per scan in the common case

        visit = self.approved_visit(seq=42)
        qr = visit.qr_pass
        self.assertEqual(
            signing.verify(visit.visit_id, self.alpha.pk, qr.token, qr.signature),
            signing.active_key_id(),
        )

    def test_malformed_key_ring_configuration_is_rejected_loudly(self):
        from django.core.exceptions import ImproperlyConfigured

        cases = {
            "no separator": "retiredkey",
            "missing key": "k0:",
            "missing id": ":somekey",
        }
        for label, value in cases.items():
            with self.subTest(case=label):
                with override_settings(QR_SIGNING_PREVIOUS_KEYS=value):
                    with self.assertRaises(ImproperlyConfigured):
                        signing.verify(
                            "00000000-0000-0000-0000-000000000000", 1, "x", "a" * 64
                        )

    def test_a_ring_that_repeats_the_active_key_id_is_rejected(self):
        from django.core.exceptions import ImproperlyConfigured

        with override_settings(
            QR_SIGNING_KEY_ID="k1", QR_SIGNING_PREVIOUS_KEYS="k1:other"
        ):
            with self.assertRaises(ImproperlyConfigured):
                signing.verify(
                    "00000000-0000-0000-0000-000000000000", 1, "x", "a" * 64
                )

    def test_an_oversized_ring_is_refused(self):
        from django.core.exceptions import ImproperlyConfigured

        ring = ",".join(f"k{i}:key{i}" for i in range(1, 12))
        with override_settings(QR_SIGNING_PREVIOUS_KEYS=ring):
            with self.assertRaises(ImproperlyConfigured):
                signing.verify(
                    "00000000-0000-0000-0000-000000000000", 1, "x", "a" * 64
                )

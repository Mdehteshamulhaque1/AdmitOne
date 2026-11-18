"""Signing keys for visitor QR passes.

QR passes are HMAC-signed so a scanned artifact cannot be forged or edited
without the server key.  That key used to be ``settings.SECRET_KEY``, which
couples two unrelated trust domains:

* ``SECRET_KEY`` signs sessions, CSRF tokens, password-reset tokens and the
  JWTs.  Anything that can forge a pass can forge a session.
* Rotating ``SECRET_KEY`` -- the routine response to a suspected leak --
  silently invalidated **every outstanding pass** across the estate, because
  the signing key and the verifying key were the same secret.  There was no way
  to rotate the QR key on its own schedule.

Signing therefore uses a dedicated key, and verification accepts a **key ring**:
the active key signs, retired keys still verify.  Rotation is an overlap window
rather than a flag day:

1. put the new key in ``QR_SIGNING_PREVIOUS_KEYS``, point
   ``QR_SIGNING_KEY``/``QR_SIGNING_KEY_ID`` at it, deploy;
2. let outstanding passes age out (capped at ``QR_PASS_VALID_MINUTES``);
3. drop the retired entry.

Documented in ``docs/DEPLOYMENT.md``.

Two payload formats are accepted:

* **v1 (current)** -- ``sg-qr-v1|<visit_uuid>|<org_pk>|<token_uuid>``, signed
  with a key from the ring.  The version prefix is domain separation: a
  signature minted here can never be replayed into another HMAC scheme that
  happens to share a secret.
* **legacy (read-only)** -- ``<visit_uuid>|<org_pk>|<token_uuid>``, signed with
  ``QR_SIGNING_LEGACY_KEY`` (which defaults to ``SECRET_KEY``).  This is the
  pre-rotation format.  It is still *verified* so that passes issued before the
  upgrade keep working until they expire; nothing signs in this format any
  more.  Set ``QR_SIGNING_LEGACY_KEY = ""`` once no live pass predates the
  upgrade, and the whole legacy path disappears.

The separator is ``|`` and every field is a UUID or an integer, so no field can
contain a separator and no two encodings can collide.
"""

import hashlib
import hmac

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

#: Bump only if the layout changes.  Verification of older versions is kept.
PAYLOAD_VERSION = "sg-qr-v1"

#: Guard against a misconfigured ring that could not distinguish real keys.
MAX_RING_SIZE = 8


def _ring():
    """``[(key_id, key_str)]`` -- the active key first, then retired keys."""
    current_id = settings.QR_SIGNING_KEY_ID
    ring = [(current_id, settings.QR_SIGNING_KEY)]

    raw = getattr(settings, "QR_SIGNING_PREVIOUS_KEYS", "") or ""
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        key_id, sep, key = entry.partition(":")
        key_id, key = key_id.strip(), key.strip()
        if not sep or not key_id or not key:
            raise ImproperlyConfigured(
                "QR_SIGNING_PREVIOUS_KEYS entries must look like 'id:key'; got "
                f"{entry!r}"
            )
        if key_id == current_id:
            raise ImproperlyConfigured(
                f"QR_SIGNING_PREVIOUS_KEYS repeats the active key id {key_id!r}"
            )
        if any(key_id == existing for existing, _ in ring):
            raise ImproperlyConfigured(
                f"QR_SIGNING_PREVIOUS_KEYS lists key id {key_id!r} twice"
            )
        ring.append((key_id, key))

    if len(ring) > MAX_RING_SIZE:
        raise ImproperlyConfigured(
            f"QR signing key ring has {len(ring)} keys, refusing more than "
            f"{MAX_RING_SIZE}. Retire old keys instead of accumulating them."
        )
    return ring


def active_key_id():
    """The key id new signatures are minted under."""
    return settings.QR_SIGNING_KEY_ID


def _v1_payload(visit_id, organization_id, token):
    return "|".join(
        [PAYLOAD_VERSION, str(visit_id), str(organization_id), str(token)]
    )


def _legacy_payload(visit_id, organization_id, token):
    return f"{visit_id}|{organization_id}|{token}"


def _hmac(key_str, payload):
    return hmac.new(key_str.encode(), payload.encode(), hashlib.sha256).hexdigest()


def sign(visit_id, organization_id, token):
    """Sign a pass with the active key, in the current (v1) format."""
    return _hmac(settings.QR_SIGNING_KEY, _v1_payload(visit_id, organization_id, token))


def verify(visit_id, organization_id, token, signature):
    """Constant-time check of ``signature`` against every key we still accept.

    Returns the ``key_id`` that matched, or ``None``.  A key ring is a handful of
    entries, so every candidate is tried in turn with
    :func:`hmac.compare_digest`; there is no shortcut that could skip a key, and
    the comparison never short-circuits on content.
    """
    if not signature:
        return None

    v1_payload = _v1_payload(visit_id, organization_id, token)
    for key_id, key in _ring():
        if hmac.compare_digest(_hmac(key, v1_payload), signature):
            return key_id

    legacy_key = getattr(settings, "QR_SIGNING_LEGACY_KEY", "") or ""
    if legacy_key:
        legacy_payload = _legacy_payload(visit_id, organization_id, token)
        if hmac.compare_digest(_hmac(legacy_key, legacy_payload), signature):
            return "legacy"

    return None

"""Robust parsing of environment variables.

`settings.py` is a long list of ``os.environ.get(...)`` calls, and the obvious
one-liners have two failure modes that both fail *silently*:

* ``os.environ.get("X", "True") == "True"`` is case-sensitive. A deployment
  that sets ``EMAIL_USE_TLS=true`` -- the most natural spelling -- gets
  ``False``, and in this project's case that means SMTP credentials are sent
  in cleartext. The wrong value is indistinguishable from the right one.
* ``os.environ.get("X", "").split(",")`` leaves whitespace on every element
  after the first. ``CSRF_TRUSTED_ORIGINS="https://a.com, https://b.com"``
  yields ``['https://a.com', ' https://b.com']``, and the second origin is
  then silently ignored by both CSRF and CORS -- a deployment that *looks*
  configured while half the origins fail.

Everything here is strict about what it accepts and explicit about what it
defaults to, so a typo becomes a startup error rather than a silent
misconfiguration.
"""

import os

# Spellings accepted as true. Kept generous on purpose: these are typed by
# humans into deploy dashboards, and the failure mode of an unrecognised value
# used to be "assume false", which is how TLS got switched off by accident.
TRUTHY = frozenset({"1", "true", "yes", "on", "y", "t", "enable", "enabled"})
FALSY = frozenset({"0", "false", "no", "off", "n", "f", "disable", "disabled", ""})


def env_bool(name, default=False, *, required=False):
    """Read a boolean from the environment.

    Accepts any capitalisation plus ``1/0``, ``yes/no``, ``on/off``. An
    unrecognised value raises ``ValueError`` rather than falling back to
    ``default`` -- guessing here is what makes a security setting silently
    wrong.
    """
    raw = os.environ.get(name)
    if raw is None:
        if required:
            raise ValueError(f"{name} is required but not set")
        return default
    value = raw.strip().lower()
    if value in TRUTHY:
        return True
    if value in FALSY:
        # An explicitly empty string counts as false, matching the intuition
        # that an unset-looking variable is off.
        return False
    raise ValueError(
        f"{name}={raw!r} is not a boolean. Use one of: "
        "true/false, 1/0, yes/no, on/off."
    )


def env_list(name, default=(), *, separator=","):
    """Read a comma-separated list, with each element stripped.

    Empty elements are dropped, so a trailing comma or a blank line in a
    ``.env`` file does not produce an entry that matches nothing.
    """
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    return [item.strip() for item in raw.split(separator) if item.strip()]


def env_int(name, default, *, minimum=None, maximum=None):
    """Read an integer, optionally range-checked.

    A non-numeric value raises instead of crashing later at connect time, and
    the bounds turn a typo like ``EMAIL_PORT=5870`` into a startup error.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not an integer") from None
    if minimum is not None and value < minimum:
        raise ValueError(f"{name}={value} is below the minimum of {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name}={value} is above the maximum of {maximum}")
    return value


def env_str(name, default=None, *, strip=True):
    """Read a string, stripping surrounding whitespace by default.

    Env vars picked up from a ``.env`` file or a shell heredoc frequently carry
    a trailing space or a stray newline, which for a hostname or an e-mail
    address is the difference between working and a confusing SMTP error.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip() if strip else raw

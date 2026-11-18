"""System checks for visitor-document storage.

The document path is only correct if a handful of deployment facts hold, and
every one of them fails silently when wrong: a 404 in production, a directory
that quietly becomes public, or a volume that is not mounted at all so uploads
appear to succeed and vanish.

``manage.py check --deploy`` is run by most hosts before traffic is cut over,
so these are worth registering -- an operator sees them at deploy time rather
than discovering a broken document link from a visitor complaint.
"""

import os

from django.conf import settings
from django.core.checks import Error, Warning, register


@register("deploy", "files", "media")
def check_document_storage(app_configs=None, **kwargs):
    """Report deployment facts that would break or expose document access.

    Reads ``django.conf.settings`` directly rather than taking it as a
    parameter: the check registry calls checks as ``check(app_configs,
    databases)``, so a ``settings`` argument would arrive empty.
    """
    problems = []

    private_root = getattr(settings, "PRIVATEMEDIA_ROOT", None)
    media_root = getattr(settings, "MEDIA_ROOT", None)

    if not private_root:
        problems.append(
            Error(
                "PRIVATEMEDIA_ROOT is not set.",
                hint=(
                    "Visitor identity documents are stored there. It must be a "
                    "persistent location that is never served as public media."
                ),
                id="visits.E001",
            )
        )
        return problems

    private_root = str(private_root)

    # The structural guarantee the whole design rests on.
    if media_root and (
        private_root == str(media_root)
        or private_root.startswith(str(media_root).rstrip("/\\") + os.sep)
        or private_root.startswith(str(media_root).rstrip("/\\") + "/")
    ):
        problems.append(
            Error(
                "PRIVATEMEDIA_ROOT is inside MEDIA_ROOT.",
                hint=(
                    "MEDIA_ROOT is exposed by a URL in development and by a CDN "
                    "or web server in production. Storing identity documents "
                    "there would publish them. Use a sibling directory."
                ),
                id="visits.E002",
            )
        )

    if getattr(settings, "ENVIRONMENT", "development") == "production":
        # MEDIA_ROOT is served in production by config/urls.py (with a dedicated
        # route that cannot reach this directory), so there is no W001 here
        # anymore. A warning that fired unconditionally on every deploy taught
        # operators to ignore warnings; it also predated the day the media route
        # actually existed. The two things that can still break in production
        # are that this directory is missing or not writable, so those stay.

        # Ephemeral container filesystems are the usual cause of uploads that
        # appear to work and then disappear on the next deploy.
        if not os.path.isdir(private_root):
            problems.append(
                Warning(
                    f"PRIVATEMEDIA_ROOT ({private_root}) does not exist.",
                    hint=(
                        "Create it, or mount a persistent volume. Uploads will "
                        "fail with an error and any existing documents will be "
                        "unreachable."
                    ),
                    id="visits.W002",
                )
            )
        elif not os.access(private_root, os.W_OK):
            problems.append(
                Error(
                    f"PRIVATEMEDIA_ROOT ({private_root}) is not writable.",
                    hint="The application user cannot write to it; uploads will fail.",
                    id="visits.E003",
                )
            )

    return problems

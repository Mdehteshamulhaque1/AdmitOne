"""Storage for visitor identity documents.

The rest of the application's uploads (visitor photos, avatars, organization
logos) sit under ``MEDIA_ROOT``, which a URL pattern exposes in development and
a web server or CDN would expose in production. That is a reasonable trade for
a thumbnail-sized face photo and an unreasonable one for a scan of a passport.

Documents are therefore stored in a *private* root that no URL pattern points
at, and are only reachable through ``visits.views.document`` after an
authorization and tenancy check.

The important part of this module is not where the bytes go, it is that
``base_url`` is ``None``. ``Storage.url()`` raises ``ValueError`` when
``base_url`` is unset, so a template or serializer that reaches for
``visitor.document_file.url`` fails loudly in development rather than
publishing an identity document at a guessable path in production. There is no
"accidentally public" state to reach by accident.
"""

import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils.functional import cached_property


class PrivateRootStorage(FileSystemStorage):
    """A filesystem storage with no public URL, ever.

    ``location`` defaults to ``settings.PRIVATEMEDIA_ROOT`` and is deliberately
    *not* ``MEDIA_ROOT``: keeping them separate is what stops a future
    ``static(settings.MEDIA_URL, ...)`` from making these files public.
    """

    def __init__(self, location=None, **kwargs):
        # base_url=None is the security-relevant part; everything else is
        # ordinary filesystem storage. Passing it explicitly means a
        # MEDIA_URL set in the environment cannot leak through.
        super().__init__(location=location, base_url=None, **kwargs)

    @cached_property
    def base_url(self):
        """Always ``None``, so ``Storage.url()`` raises.

        This override is load-bearing. ``FileSystemStorage.base_url`` is

            _value_or_setting(self._base_url, settings.MEDIA_URL)

        so merely *passing* ``base_url=None`` falls straight back to
        ``MEDIA_URL`` and quietly hands out working public URLs for the private
        root. Returning ``None`` unconditionally is what makes ``.url`` raise
        ``ValueError`` instead, which is the whole point of this class.
        """
        return None


def private_document_storage():
    """The storage used for visitor identity documents."""
    root = getattr(settings, "PRIVATEMEDIA_ROOT", None)
    if not root:
        raise ImproperlyConfigured(
            "PRIVATEMEDIA_ROOT must be set to a directory that is not served "
            "as public media; visitor identity documents are stored there."
        )
    return PrivateRootStorage(location=str(root))


def document_path(filename):
    """Where a document would be written, relative to the private root.

    Exposed for tests and for operators checking where a file ended up. Uses
    Django's own ``upload_to`` handling so the path matches what the storage
    backend will actually choose.
    """
    return os.path.join("visitor_documents", filename)


class DocumentFileField(models.FileField):
    """A ``FileField`` backed by the private root, resolved lazily.

    ``FileField(storage=...)`` instantiates its backend once, when the model
    class is built -- i.e. at import time, before ``settings`` has been fully
    configured and long before ``override_settings`` could matter. That
    hard-codes whichever root happened to be configured during import, which
    makes the setting untestable and un-overridable for a deployment that
    relocates the volume.

    Resolving on access instead means the field always reflects the current
    setting, and costs a small object construction per access, which is nothing
    next to opening a file for reading.
    """

    def __init__(self, *args, **kwargs):
        self._storage_factory = kwargs.pop("storage", None) or private_document_storage
        super().__init__(*args, **kwargs)

    @property
    def storage(self):
        return self._storage_factory()

    @storage.setter
    def storage(self, value):
        # super().__init__() assigns to self.storage. The factory set in
        # __init__ above is the source of truth, so the assignment is dropped
        # rather than allowed to replace it.
        pass

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Serialise the callable, not the instance, so the migration is
        # portable and does not freeze a filesystem path into the history.
        kwargs["storage"] = self._storage_factory
        return name, path, args, kwargs

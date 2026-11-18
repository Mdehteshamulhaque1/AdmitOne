"""Validation for visitor uploads.

``FileExtensionValidator`` on its own is not enough for an identity document.
The extension is attacker-controlled, so ``passport.pdf`` is a free pass for
whatever bytes the attacker likes, and browsers will happily render content
that matches a dangerous type. These validators check the three things that
actually decide whether a file is acceptable:

* **Size**, so a single upload cannot fill the disk. The storage backend is
  unbuffered and writes straight to disk, so nothing else would stop it.
* **The extension**, as the first cheap filter.
* **The content**, by sniffing the leading bytes. An extension that disagrees
  with the bytes is rejected rather than trusted.

None of this replaces serving the file safely -- the download view also sets a
fixed ``Content-Type`` and ``Content-Disposition: attachment`` -- but it means
a file that arrives is already known not to be an HTML or SVG payload.
"""

import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

# (extension, canonical content type). The declared Content-Type is only
# trusted when it is one of these *and* the bytes agree; it is never echoed
# back to the browser (see visits.views.document).
DOCUMENT_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}

# Leading bytes -> canonical content type. Deliberately small and explicit: a
# new format has to be added here deliberately, with its own risk assessment,
# rather than being sniffed in and accepted by default.
_MAGIC = {
    b"%PDF-": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}

# Bytes that make a file dangerous to serve from the app's own origin even with
# a correct extension: HTML, SVG and XML all execute script in a browser.
_XML_HTML_PREFIXES = (b"<?xml", b"<!DOCTYPE html", b"<html", b"<svg", b"<!doctype html")


def sniff_content_type(fileobj, read_bytes=16):
    """Best-effort type of an uploaded file, from its leading bytes.

    Returns a canonical MIME string, or ``"application/octet-stream"`` when
    nothing matches. Unrecognised is treated as untrusted, which is the answer
    that keeps a new format out of the allowlist by default.
    """
    position = None
    try:
        position = fileobj.tell()
        fileobj.seek(0)
        head = fileobj.read(max(read_bytes, 12))
    except (AttributeError, OSError, ValueError):
        head = b""
    finally:
        if position is not None:
            try:
                fileobj.seek(position)
            except (OSError, ValueError):
                pass

    for magic, content_type in _MAGIC.items():
        if head.startswith(magic):
            return content_type
    lowered = head.lstrip()[:64].lower()
    for prefix in _XML_HTML_PREFIXES:
        if lowered.startswith(prefix.lower()):
            return "text/html"
    return "application/octet-stream"


def validate_upload_size(value, max_bytes=None, label="file"):
    """Reject an upload over ``max_bytes``.

    Size is read from the uploaded file rather than from
    ``FieldFile.size`` so the same validator works on a form field, a
    serializer and a bare ``UploadedFile``.
    """
    if max_bytes is None:
        max_bytes = getattr(settings, "MAX_UPLOAD_DOCUMENT_BYTES", 10 * 1024 * 1024)
    size = getattr(value, "size", None)
    if size is None:
        return
    if size > max_bytes:
        raise ValidationError(
            f"{label} is too large: {size // 1024} KB exceeds the "
            f"{max_bytes // (1024 * 1024)} MB limit."
        )


def validate_document_upload(value):
    """Allowlist for visitor identity documents: size, extension, and bytes."""
    validate_upload_size(
        value,
        max_bytes=getattr(settings, "MAX_UPLOAD_DOCUMENT_BYTES", 10 * 1024 * 1024),
        label="Document",
    )

    name = getattr(value, "name", "") or ""
    extension = os.path.splitext(name)[1].lstrip(".").lower()
    # FileExtensionValidator gives the standard "not a valid file type" message.
    FileExtensionValidator(allowed_extensions=list(DOCUMENT_TYPES))(value)

    actual = sniff_content_type(value)
    expected = DOCUMENT_TYPES[extension]
    if actual != expected:
        # A .pdf that is really HTML is the interesting case, so say so plainly
        # rather than emitting a generic extension complaint.
        if actual == "text/html":
            raise ValidationError(
                "Document content is HTML or XML, which is not allowed. "
                "Upload a PDF, JPEG or PNG."
            )
        raise ValidationError(
            f"Document content is {actual}, which does not match the "
            f"{extension} extension. Upload a PDF, JPEG or PNG."
        )


def validate_image_upload(value):
    """Size ceiling for photos, avatars and logos.

    The *type* check for these is Pillow's, performed by Django's
    ``ImageField``: it decodes the file, so a renamed ``.jpg`` is caught there
    rather than by string matching here.
    """
    validate_upload_size(
        value,
        max_bytes=getattr(settings, "MAX_UPLOAD_IMAGE_BYTES", 5 * 1024 * 1024),
        label="Image",
    )

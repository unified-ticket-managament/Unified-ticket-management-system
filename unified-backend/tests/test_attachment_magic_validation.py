# test_attachment_magic_validation.py
#
# Phase 2 hardening: magic-byte/content-sniffing as a second attachment
# validation gate (validators.validate_attachment_magic_bytes). No DB,
# no real network call.
#
# libmagic is genuinely NOT installed on this dev machine (confirmed:
# `import magic` itself raises ImportError here) — the fail-open tests
# below exercise the REAL current environment, not a simulation. The
# "real detection" tests monkeypatch `sys.modules["magic"]` with a fake
# module exposing `from_buffer`, since the import inside
# validate_attachment_magic_bytes is a local (lazy) import specifically
# so a host with no libmagic degrades gracefully — this is the standard
# way to stub a lazily-imported module for a test.

import sys
import types

import pytest

from app.ticketing.utils import validators
from app.ticketing.utils.validators import validate_attachment_magic_bytes


@pytest.fixture(autouse=True)
def _reset_warned_once_flag():
    """Each test gets a clean slate for the "log once" flag."""
    validators._magic_unavailable_warned = False
    yield
    validators._magic_unavailable_warned = False


def _install_fake_magic(monkeypatch, sniffed_mime: str):
    fake_module = types.SimpleNamespace(from_buffer=lambda data, mime=True: sniffed_mime)
    monkeypatch.setitem(sys.modules, "magic", fake_module)


# ---------------------------------------------------------
# Real (fail-open) behavior on THIS machine — libmagic genuinely absent
# ---------------------------------------------------------


def test_libmagic_unavailable_skips_check_without_raising():
    """
    Confirmed environment fact: libmagic is not installed here, so
    `import magic` inside the validator raises ImportError. The
    validator must fail open (skip, not block the upload) rather than
    propagate that ImportError to the caller.
    """

    # Text bytes claimed as a .png — would fail a real magic-byte check,
    # but must pass here since the check itself is unavailable.
    validate_attachment_magic_bytes("fake.png", "png", b"not a real png")


# ---------------------------------------------------------
# Simulated real detection (fake magic module installed)
# ---------------------------------------------------------


def test_real_png_bytes_pass(monkeypatch):
    _install_fake_magic(monkeypatch, "image/png")
    validate_attachment_magic_bytes("photo.png", "png", b"\x89PNG\r\n\x1a\n...")


def test_text_content_claimed_as_png_is_rejected(monkeypatch):
    _install_fake_magic(monkeypatch, "text/plain")
    with pytest.raises(ValueError, match="does not look like a real .png file"):
        validate_attachment_magic_bytes("fake.png", "png", b"just some text")


def test_text_content_claimed_as_pdf_is_rejected(monkeypatch):
    _install_fake_magic(monkeypatch, "text/plain")
    with pytest.raises(ValueError):
        validate_attachment_magic_bytes("fake.pdf", "pdf", b"just some text")


def test_text_content_claimed_as_jpg_is_rejected(monkeypatch):
    _install_fake_magic(monkeypatch, "text/plain")
    with pytest.raises(ValueError):
        validate_attachment_magic_bytes("fake.jpg", "jpg", b"just some text")


def test_real_docx_zip_container_passes_family_check(monkeypatch):
    """
    The key false-positive guard: a real .docx (itself a ZIP container)
    must not be rejected just because its sniffed MIME is a generic
    zip type rather than an exact Office MIME string.
    """

    _install_fake_magic(monkeypatch, "application/zip")
    validate_attachment_magic_bytes("resume.docx", "docx", b"PK\x03\x04...")


def test_real_xlsx_openxml_mime_passes_family_check(monkeypatch):
    _install_fake_magic(
        monkeypatch,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    validate_attachment_magic_bytes("data.xlsx", "xlsx", b"PK\x03\x04...")


def test_real_doc_ole_container_passes_family_check(monkeypatch):
    _install_fake_magic(monkeypatch, "application/msword")
    validate_attachment_magic_bytes("letter.doc", "doc", b"\xd0\xcf\x11\xe0...")


def test_exe_content_claimed_as_docx_is_rejected(monkeypatch):
    _install_fake_magic(monkeypatch, "application/x-dosexec")
    with pytest.raises(ValueError):
        validate_attachment_magic_bytes("invoice.docx", "docx", b"MZ\x90\x00...")


@pytest.mark.parametrize("extension", ["txt", "csv", "eml", "dat"])
def test_skip_extensions_never_sniffed_or_rejected(monkeypatch, extension):
    """These have no reliable fixed byte signature — never sniffed,
    regardless of what bytes are actually present."""

    _install_fake_magic(monkeypatch, "application/x-dosexec")  # would fail everything else
    validate_attachment_magic_bytes(f"file.{extension}", extension, b"MZ\x90\x00...")


def test_real_gif_bytes_pass(monkeypatch):
    _install_fake_magic(monkeypatch, "image/gif")
    validate_attachment_magic_bytes("anim.gif", "gif", b"GIF89a...")


def test_real_zip_bytes_pass(monkeypatch):
    _install_fake_magic(monkeypatch, "application/zip")
    validate_attachment_magic_bytes("archive.zip", "zip", b"PK\x03\x04...")

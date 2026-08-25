# test_attachment_allowlist_expansion.py
#
# Phase 3: the full-matrix attachment allow-list expansion in
# constants.py — documents, spreadsheets, presentations, images,
# video, audio, archives, code/text. Pure-logic coverage of
# validate_attachment_type (the real security gate; extension-based,
# not MIME-based) plus explicit regression guards that macro-enabled
# Office formats, .msg, and executables remain rejected. No DB, no
# network.

import pytest

from app.ticketing.utils.validators import validate_attachment_type


@pytest.mark.parametrize("extension", ["rtf", "odt", "ods", "ppt", "pptx", "odp"])
def test_validate_attachment_type_accepts_new_document_extensions(extension):
    validate_attachment_type(f"file.{extension}", None)


@pytest.mark.parametrize(
    "extension",
    ["bmp", "webp", "tiff", "tif", "ico", "heic", "heif", "svg"],
)
def test_validate_attachment_type_accepts_new_image_extensions(extension):
    validate_attachment_type(f"file.{extension}", None)


@pytest.mark.parametrize(
    "extension",
    ["mp4", "mov", "avi", "wmv", "mkv", "mp3", "wav", "m4a", "aac"],
)
def test_validate_attachment_type_accepts_new_video_and_audio_extensions(extension):
    validate_attachment_type(f"file.{extension}", None)


@pytest.mark.parametrize("extension", ["rar", "7z", "tar", "gz", "bz2"])
def test_validate_attachment_type_accepts_new_archive_extensions(extension):
    validate_attachment_type(f"file.{extension}", None)


@pytest.mark.parametrize(
    "extension",
    ["py", "js", "ts", "java", "html", "css", "json", "xml", "sql", "md", "log"],
)
def test_validate_attachment_type_accepts_new_code_text_extensions(extension):
    validate_attachment_type(f"file.{extension}", None)


@pytest.mark.parametrize("extension", ["docm", "xlsm", "pptm"])
def test_validate_attachment_type_still_rejects_macro_enabled_office(extension):
    """
    Regression guard: macro-enabled Office formats are a real malware
    vector and must never be added to the allow-list, even as part of
    the broader Phase 3 expansion.
    """
    with pytest.raises(ValueError):
        validate_attachment_type(f"file.{extension}", None)


def test_validate_attachment_type_still_rejects_msg():
    # Outlook's native binary message format — no parser exists in
    # this codebase, deliberately not added.
    with pytest.raises(ValueError):
        validate_attachment_type("email.msg", None)


@pytest.mark.parametrize("extension", ["exe", "bat", "msi"])
def test_validate_attachment_type_still_rejects_executables(extension):
    with pytest.raises(ValueError):
        validate_attachment_type(f"file.{extension}", "application/octet-stream")

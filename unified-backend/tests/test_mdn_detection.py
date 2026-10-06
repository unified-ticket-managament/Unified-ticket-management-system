# test_mdn_detection.py
#
# Pure (no DB, no network) coverage of read-receipt detection and MDN
# parsing. Fixtures are SANITIZED and deterministic: they reproduce the
# STRUCTURE of the real Outlook receipt verified live in Phase 0
# (multipart/report; report-type=disposition-notification, a
# message/disposition-notification part, Graph item class
# REPORT.IPM.Note.IPNRN) with example.com addresses — no real mailbox
# content.

import pytest

from app.ticketing.schemas.mail_integration import IncomingMailPayload
from app.ticketing.services.bounce_detection import is_bounce_notification
from app.ticketing.services.mail_mapping_service import (
    map_external_email_to_interaction,
)
from app.ticketing.services.mdn_detection import (
    MAX_MDN_MIME_BYTES,
    is_read_receipt_candidate,
    parse_mdn,
)

ORIGINAL_ID = "<ORIGINAL123@PN0SPRMB0019.INDPRD01.PROD.OUTLOOK.COM>"
STANDARD_DISPOSITION = "automatic-action/MDN-sent-automatically; displayed"


def _crlf(text: str) -> bytes:
    return text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")


def _receipt(
    *,
    dsn_fields: str | None = None,
    outer_extra: str = "",
    date: str = "Tue, 6 Oct 2026 08:21:37 +0000",
) -> bytes:
    if dsn_fields is None:
        dsn_fields = (
            "Final-recipient: RFC822; recipient@example.com\n"
            f"Disposition: {STANDARD_DISPOSITION}\n"
            "X-MSExch-Correlation-Key: AAAAAAAAAAAAAAAAAAAAAA==\n"
            f"Original-Message-ID:\n\t{ORIGINAL_ID}\n"
            "X-Display-Name: Recipient\n"
        )
    return _crlf(
        "From: Recipient <recipient@example.com>\n"
        "To: Sender <sender@example.com>\n"
        "Subject: Read: Hello\n"
        f"Date: {date}\n"
        "Message-ID: <RECEIPT-OWN-ID@example.com>\n"
        f"{outer_extra}"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/report;\n\tboundary="BOUNDARY";\n'
        "\treport-type=disposition-notification\n"
        "\n--BOUNDARY\n"
        'Content-Type: text/plain; charset="us-ascii"\n\n'
        "Your message was read.\n"
        "\n--BOUNDARY\n"
        "Content-Type: message/disposition-notification\n\n"
        f"{dsn_fields}"
        "\n--BOUNDARY--\n"
    )


# ---------------------------------------------------------------
# Detection (cheap pre-check, no MIME)
# ---------------------------------------------------------------


@pytest.mark.parametrize(
    "item_class",
    [
        "REPORT.IPM.Note.IPNRN",  # observed live (read receipt)
        "report.ipm.note.ipnrn",  # case-insensitive
        " REPORT.IPM.Note.IPNRN ",
        "REPORT.IPM.Note.IPNNRN",  # sibling class: detected (consumed)
    ],
)
def test_receipt_item_classes_are_candidates(item_class):
    assert is_read_receipt_candidate(item_class) is True


@pytest.mark.parametrize(
    "item_class",
    [
        None,
        "",
        "IPM.Note",  # ordinary mail
        "REPORT",  # malformed/truncated
        "REPORT.IPM.Note.NDR",  # a genuine bounce class stays a bounce
        "IPM.Schedule.Meeting.Request",
        42,  # wrong type must not raise
    ],
)
def test_other_item_classes_are_not_candidates(item_class):
    assert is_read_receipt_candidate(item_class) is False


def test_misleading_ms_tnef_header_alone_is_not_a_signal():
    # Graph reports this for the real Outlook receipt — it must never
    # be the (only) evidence either way.
    assert is_read_receipt_candidate(None, "application/ms-tnef") is False
    # ...but the item class still wins when the header is misleading.
    assert is_read_receipt_candidate("REPORT.IPM.Note.IPNRN", "application/ms-tnef") is True


def test_standards_report_type_header_is_a_secondary_signal():
    header = "multipart/report;\r\n\tboundary=x;\r\n\treport-type=disposition-notification"
    assert is_read_receipt_candidate(None, header) is True
    assert is_read_receipt_candidate(None, "multipart/report; report-type=delivery-status") is False


def test_subject_text_is_never_a_signal():
    # is_read_receipt_candidate takes no subject at all by design.
    with pytest.raises(TypeError):
        is_read_receipt_candidate("IPM.Note", None, "Read: Hello")  # type: ignore[call-arg]


# ---------------------------------------------------------------
# Bounce classification must never swallow a standards MDN, and a
# genuine NDR must still be a bounce.
# ---------------------------------------------------------------


def test_standards_mdn_report_is_not_classified_as_a_bounce():
    assert (
        is_bounce_notification(
            "someone@example.com",
            "Read: Hello",
            "multipart/report; report-type=disposition-notification",
        )
        is False
    )


@pytest.mark.parametrize(
    "from_email, subject, content_type",
    [
        ("mailer-daemon@example.com", "Anything", None),
        ("postmaster@example.com", "Anything", None),
        ("someone@example.com", "Undeliverable: Hello", None),
        ("someone@example.com", "Hello", "multipart/report; report-type=delivery-status"),
        ("someone@example.com", "Hello", "multipart/report"),
    ],
)
def test_genuine_ndrs_are_still_bounces(from_email, subject, content_type):
    assert is_bounce_notification(from_email, subject, content_type) is True


def test_ordinary_mail_is_neither():
    assert is_bounce_notification("client@example.com", "Question", "text/html") is False
    assert is_read_receipt_candidate("IPM.Note", "text/html") is False


# ---------------------------------------------------------------
# Mapping: item class survives the Graph -> EmailRequest boundary
# ---------------------------------------------------------------


def _payload(item_class=None, header_content_type="application/ms-tnef", **kw):
    data = {
        "id": "graph-id",
        "internetMessageId": "<receipt@example.com>",
        "subject": "Read: Hello",
        "from": {"emailAddress": {"address": "recipient@example.com"}},
        "toRecipients": [{"emailAddress": {"address": "inbox@example.com"}}],
        "body": {"contentType": "html", "content": "<p>x</p>"},
        "internetMessageHeaders": [
            {"name": "Content-Type", "value": header_content_type}
        ],
    }
    if item_class:
        data["singleValueExtendedProperties"] = [
            {"id": "String 0x001A", "value": item_class}
        ]
    data.update(kw)
    return IncomingMailPayload.model_validate(data)


@pytest.mark.parametrize(
    "echoed_id",
    [
        "String 0x1a",  # what Graph REALLY returns (observed live in Phase 0 / implementation)
        "String 0x1A",
        "String 0x001A",  # the spelling we ask with
        "string 0x001a",
        " String 0x001A ",
    ],
)
def test_item_class_matches_however_graph_spells_the_property_id(echoed_id):
    # Regression: Graph echoes the id normalized ("String 0x1a"); comparing
    # against "String 0x001A" silently found no item class on real receipts.
    payload = IncomingMailPayload.model_validate(
        {
            "internetMessageId": "<r@example.com>",
            "subject": "Read: Hello",
            "from": {"emailAddress": {"address": "recipient@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "inbox@example.com"}}],
            "body": {"contentType": "html", "content": "<p>x</p>"},
            "singleValueExtendedProperties": [
                {"id": echoed_id, "value": "REPORT.IPM.Note.IPNRN"}
            ],
        }
    )
    assert payload.item_class == "REPORT.IPM.Note.IPNRN"
    assert map_external_email_to_interaction(payload).is_read_receipt is True


def test_other_extended_properties_are_never_mistaken_for_the_item_class():
    payload = IncomingMailPayload.model_validate(
        {
            "internetMessageId": "<r@example.com>",
            "subject": "Hello",
            "from": {"emailAddress": {"address": "someone@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "inbox@example.com"}}],
            "body": {"contentType": "text", "content": "x"},
            "singleValueExtendedProperties": [
                {"id": "String 0x1035", "value": "REPORT.IPM.Note.IPNRN"},
                {"id": "Binary 0x1a", "value": "REPORT.IPM.Note.IPNRN"},
            ],
        }
    )
    assert payload.item_class is None


def test_mapper_flags_outlook_receipt_despite_misleading_header():
    email = map_external_email_to_interaction(_payload("REPORT.IPM.Note.IPNRN"))

    assert email.is_read_receipt is True
    # The misleading application/ms-tnef header must not make it a bounce.
    assert email.is_bounce is False


def test_mapper_leaves_ordinary_mail_alone():
    email = map_external_email_to_interaction(
        _payload("IPM.Note", header_content_type="text/html", subject="Question")
    )
    assert email.is_read_receipt is False and email.is_bounce is False


def test_mapper_missing_or_malformed_item_class_is_ordinary_mail():
    assert map_external_email_to_interaction(_payload(None)).is_read_receipt is False
    assert map_external_email_to_interaction(_payload("???")).is_read_receipt is False


def test_mapper_keeps_a_real_ndr_a_bounce():
    email = map_external_email_to_interaction(
        _payload(
            "REPORT.IPM.Note.NDR",
            header_content_type="multipart/report; report-type=delivery-status",
            subject="Undeliverable: Hello",
        )
    )
    assert email.is_bounce is True
    assert email.is_read_receipt is False


# ---------------------------------------------------------------
# Parser
# ---------------------------------------------------------------


def test_parses_the_verified_outlook_structure():
    parsed = parse_mdn(_receipt())

    assert parsed is not None
    assert parsed.original_message_id == ORIGINAL_ID
    assert parsed.final_recipient == "recipient@example.com"
    assert parsed.disposition == STANDARD_DISPOSITION
    assert parsed.disposition_type == "displayed"
    assert parsed.is_displayed is True
    assert parsed.mdn_message_id == "<RECEIPT-OWN-ID@example.com>"
    assert parsed.receipt_date is not None
    assert parsed.receipt_date.isoformat() == "2026-10-06T08:21:37+00:00"


def test_folded_original_message_id_is_unfolded():
    # The verified receipt folds this header onto a continuation line.
    assert parse_mdn(_receipt()).original_message_id == ORIGINAL_ID


def test_extra_whitespace_and_header_casing_are_tolerated():
    fields = (
        "FINAL-RECIPIENT:   rfc822;    Recipient@Example.COM   \n"
        "DISPOSITION:  manual-action/MDN-sent-manually;   Displayed  \n"
        f"original-message-id:    {ORIGINAL_ID}   \n"
    )
    parsed = parse_mdn(_receipt(dsn_fields=fields))

    assert parsed.final_recipient == "recipient@example.com"
    assert parsed.original_message_id == ORIGINAL_ID
    assert parsed.disposition_type == "displayed"


def test_bracketless_original_message_id_is_normalized_for_exact_matching():
    fields = (
        "Final-recipient: RFC822; recipient@example.com\n"
        f"Disposition: {STANDARD_DISPOSITION}\n"
        "Original-Message-ID: ORIGINAL123@host.example.com\n"
    )
    assert (
        parse_mdn(_receipt(dsn_fields=fields)).original_message_id
        == "<ORIGINAL123@host.example.com>"
    )


def test_final_recipient_without_rfc822_prefix_is_accepted():
    fields = (
        "Final-recipient: recipient@example.com\n"
        f"Disposition: {STANDARD_DISPOSITION}\n"
        f"Original-Message-ID: {ORIGINAL_ID}\n"
    )
    assert parse_mdn(_receipt(dsn_fields=fields)).final_recipient == "recipient@example.com"


def test_missing_original_message_id():
    fields = (
        "Final-recipient: RFC822; recipient@example.com\n"
        f"Disposition: {STANDARD_DISPOSITION}\n"
    )
    parsed = parse_mdn(_receipt(dsn_fields=fields))
    assert parsed is not None and parsed.original_message_id is None
    assert parsed.final_recipient == "recipient@example.com"


def test_missing_final_recipient():
    fields = f"Disposition: {STANDARD_DISPOSITION}\nOriginal-Message-ID: {ORIGINAL_ID}\n"
    parsed = parse_mdn(_receipt(dsn_fields=fields))
    assert parsed is not None and parsed.final_recipient is None
    assert parsed.original_message_id == ORIGINAL_ID


def test_missing_disposition_is_never_displayed():
    fields = (
        "Final-recipient: RFC822; recipient@example.com\n"
        f"Original-Message-ID: {ORIGINAL_ID}\n"
    )
    parsed = parse_mdn(_receipt(dsn_fields=fields))
    assert parsed.disposition is None and parsed.is_displayed is False


@pytest.mark.parametrize(
    "disposition, expected_type, displayed",
    [
        ("automatic-action/MDN-sent-automatically; displayed", "displayed", True),
        ("manual-action/MDN-sent-manually; displayed", "displayed", True),
        ("manual-action/MDN-sent-manually; denied", "denied", False),
        ("automatic-action/MDN-sent-automatically; deleted", "deleted", False),
        ("manual-action/MDN-sent-manually; dispatched/error", "dispatched", False),
        ("no-semicolon-at-all", None, False),
    ],
)
def test_only_an_explicit_displayed_disposition_counts(disposition, expected_type, displayed):
    fields = (
        "Final-recipient: RFC822; recipient@example.com\n"
        f"Disposition: {disposition}\n"
        f"Original-Message-ID: {ORIGINAL_ID}\n"
    )
    parsed = parse_mdn(_receipt(dsn_fields=fields))
    assert parsed.disposition_type == expected_type
    assert parsed.is_displayed is displayed
    # The raw disposition is always preserved verbatim (whitespace-normalized).
    assert parsed.disposition == disposition


def test_duplicate_fields_use_the_first_occurrence():
    fields = (
        "Final-recipient: RFC822; first@example.com\n"
        "Final-recipient: RFC822; second@example.com\n"
        f"Disposition: {STANDARD_DISPOSITION}\n"
        f"Original-Message-ID: {ORIGINAL_ID}\n"
    )
    assert parse_mdn(_receipt(dsn_fields=fields)).final_recipient == "first@example.com"


def test_message_without_a_disposition_part_yields_empty_fields_not_an_error():
    plain = _crlf(
        "From: a@example.com\nTo: b@example.com\nSubject: hi\n"
        "Content-Type: text/plain\n\nJust text.\n"
    )
    parsed = parse_mdn(plain)
    assert parsed is not None
    assert parsed.original_message_id is None
    assert parsed.final_recipient is None and parsed.disposition is None


@pytest.mark.parametrize(
    "garbage",
    [None, b"", b"\x00\xff\xfe not mime at all \x00", b"Content-Type: multipart/report\r\n\r\n"],
)
def test_malformed_or_empty_mime_never_raises(garbage):
    result = parse_mdn(garbage)
    # Either None (unusable) or an all-None parse — never an exception.
    assert result is None or (
        result.original_message_id is None and result.final_recipient is None
    )


def test_oversized_mime_is_refused():
    assert parse_mdn(b"x" * (MAX_MDN_MIME_BYTES + 1)) is None


def test_bad_date_header_degrades_to_none():
    parsed = parse_mdn(_receipt(date="not a date"))
    assert parsed is not None and parsed.receipt_date is None


def test_parser_result_never_carries_body_or_subject():
    parsed = parse_mdn(_receipt())
    assert not hasattr(parsed, "body") and not hasattr(parsed, "subject")
    assert "Your message was read" not in repr(parsed)
    assert "Hello" not in repr(parsed)

# test_cloud_link_attachment_extraction.py
#
# Pure-logic coverage for mail_mapping_service.extract_cloud_link_
# attachments — the OneDrive/SharePoint "Attach as cloud link"
# detection added after confirming live that Outlook creates no real
# Graph attachment object for these at all (hasAttachments=False,
# empty attachments collection); the file only ever exists as an <a>
# anchor in the HTML body. No database needed, same "plain data in,
# plain result out" style as test_otp_classifier.py.

from app.ticketing.services.mail_mapping_service import (
    extract_cloud_link_attachments,
    map_external_email_to_interaction,
)
from app.ticketing.schemas.mail_integration import (
    GraphEmailAddress,
    GraphItemBody,
    GraphRecipient,
    IncomingMailPayload,
)
from app.ticketing.utils.constants import MAX_ATTACHMENT_FILES

# A trimmed version of the real markup captured live from a genuine
# Outlook "Attach as cloud link" send to ticketing@probeps.com
# (2026-08-21) — confirmed via direct Graph API query that the
# message's own attachments collection was empty (hasAttachments:
# False) for this exact email.
REAL_OWALINK_HTML = (
    '<html><body><div class="elementToProof">hello'
    '<span class="entityDelimiterBefore">\u200b</span>'
    '<span class="_Entity _EType_OWALink _EId_OWALink _EReadonly_1">'
    '<span><a href="https://pediatriccenterround-my.sharepoint.com/:x:/g/'
    'personal/umesh_probeps_com/IQDyDPOZcJTWTYUtCjKMDLQQAcuqqYqELeU3vwGjeBFvSGY'
    '?xsdata=abc" rel="noopener noreferrer">'
    '<img alt="" src="https://res.public.onecdn.static.microsoft/xlsx.png">'
    'Staff and client details 1.xlsx</a></span></span>'
    '<span class="entityDelimiterAfter">\u200b</span></div>'
    "Disclaimer text.</body></html>"
)


def test_extracts_real_captured_owalink_markup():
    candidates = extract_cloud_link_attachments(REAL_OWALINK_HTML)

    assert len(candidates) == 1
    assert candidates[0].filename == "Staff and client details 1.xlsx"
    assert candidates[0].url.startswith(
        "https://pediatriccenterround-my.sharepoint.com/"
    )


def test_plain_html_with_no_cloud_link_extracts_nothing():
    html = "<html><body><p>Just a normal message, no attachments.</p></body></html>"

    assert extract_cloud_link_attachments(html) == []


def test_ordinary_non_cloud_link_is_ignored():
    html = '<html><body><a href="https://example.com/report.pdf">report.pdf</a></body></html>'

    assert extract_cloud_link_attachments(html) == []


def test_1drv_ms_short_link_is_recognized():
    html = '<html><body><a href="https://1drv.ms/w/s!AbCdEfGh">Notes.docx</a></body></html>'

    candidates = extract_cloud_link_attachments(html)

    assert len(candidates) == 1
    assert candidates[0].filename == "Notes.docx"


def test_icon_only_anchor_with_no_visible_text_falls_back_to_url_segment():
    """
    A real, observed OWA rendering pattern: the icon+filename baked
    into a single image with no text node at all. The filename must
    still come from somewhere rather than the file reference vanishing
    entirely — falls back to the URL's own last path segment.
    """

    html = (
        '<html><body><a href="https://contoso-my.sharepoint.com/:w:/g/'
        'personal/x/Quarterly_Report.docx">'
        '<img alt="" src="cid:card.png"></a></body></html>'
    )

    candidates = extract_cloud_link_attachments(html)

    assert len(candidates) == 1
    assert candidates[0].filename == "Quarterly_Report.docx"


def test_duplicate_href_is_not_extracted_twice():
    html = (
        '<html><body>'
        '<a href="https://contoso-my.sharepoint.com/x/a.pdf">a.pdf</a>'
        '<a href="https://contoso-my.sharepoint.com/x/a.pdf">a.pdf (again)</a>'
        "</body></html>"
    )

    candidates = extract_cloud_link_attachments(html)

    assert len(candidates) == 1


def test_capped_at_max_attachment_files():
    links = "".join(
        f'<a href="https://contoso-my.sharepoint.com/x/file{i}.pdf">file{i}.pdf</a>'
        for i in range(MAX_ATTACHMENT_FILES + 5)
    )
    html = f"<html><body>{links}</body></html>"

    candidates = extract_cloud_link_attachments(html)

    assert len(candidates) == MAX_ATTACHMENT_FILES


def _incoming_payload(**overrides) -> IncomingMailPayload:
    base = dict(
        id="msg-1",
        internetMessageId="<msg-1@example.com>",
        subject="hello",
        **{"from": GraphRecipient(emailAddress=GraphEmailAddress(address="client@example.com"))},
        toRecipients=[GraphRecipient(emailAddress=GraphEmailAddress(address="ticketing@probeps.com"))],
        body=GraphItemBody(contentType="html", content=REAL_OWALINK_HTML),
        hasAttachments=False,
    )
    base.update(overrides)
    return IncomingMailPayload(**base)


def test_map_external_email_to_interaction_populates_linked_attachments_for_html_body():
    email_request = map_external_email_to_interaction(_incoming_payload())

    assert len(email_request.linked_attachments) == 1
    assert email_request.linked_attachments[0].filename == "Staff and client details 1.xlsx"


def test_map_external_email_to_interaction_leaves_linked_attachments_empty_for_plain_text_body():
    email_request = map_external_email_to_interaction(
        _incoming_payload(body=GraphItemBody(contentType="text", content="hello, no links here"))
    )

    assert email_request.linked_attachments == []

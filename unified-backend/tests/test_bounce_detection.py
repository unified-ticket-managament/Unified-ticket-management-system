# test_bounce_detection.py
#
# Pure-function coverage for bounce_detection.is_bounce_notification —
# no DB, no async. False positives are the real risk (a misclassified
# genuine client email skips ticket creation/rules/SLA entirely), so
# this deliberately includes a near-miss negative case alongside the
# positive ones.

from app.ticketing.services.bounce_detection import is_bounce_notification


def test_postmaster_sender_is_bounce():
    assert is_bounce_notification("postmaster@example.com", "Hello", None) is True


def test_mailer_daemon_sender_case_insensitive_is_bounce():
    assert is_bounce_notification("MAILER-DAEMON@example.com", "Hello", None) is True


def test_subject_prefix_undeliverable_is_bounce():
    assert is_bounce_notification(
        "mail@example.com", "Undeliverable: your message", None
    ) is True


def test_subject_prefix_delivery_status_notification_is_bounce():
    assert is_bounce_notification(
        "mail@example.com", "Delivery Status Notification (Failure)", None
    ) is True


def test_subject_prefix_mail_delivery_failed_is_bounce():
    assert is_bounce_notification(
        "mail@example.com", "Mail delivery failed: returning message to sender", None
    ) is True


def test_content_type_report_type_delivery_status_is_bounce():
    assert is_bounce_notification(
        "mail@example.com",
        "Some subject",
        'multipart/report; report-type=delivery-status; boundary="x"',
    ) is True


def test_content_type_multipart_report_is_bounce():
    assert is_bounce_notification(
        "mail@example.com", "Some subject", 'multipart/report; boundary="x"'
    ) is True


def test_real_client_email_is_not_bounce():
    assert is_bounce_notification(
        "patient@example.com", "Question about my account", "text/html"
    ) is False


def test_real_client_email_with_bounce_like_word_mid_subject_is_not_bounce():
    """
    Near-miss regression guard: the word "failed"/"deliver" appearing
    mid-subject in a genuine client message must never trigger a false
    positive — only a strict prefix match on the subject counts.
    """

    assert is_bounce_notification(
        "patient@example.com",
        "Please deliver this — mail failed to reach me last time",
        "text/plain",
    ) is False


def test_none_from_email_and_subject_is_not_bounce():
    assert is_bounce_notification(None, None, None) is False

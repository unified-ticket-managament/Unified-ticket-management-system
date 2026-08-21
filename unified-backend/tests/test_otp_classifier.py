# test_otp_classifier.py
#
# Pure evaluation-logic tests for the semantic OTP-vs-mention
# classifier — no database needed. Mirrors test_rule_conditions.py's
# own "plain data in, plain bool/score out" style.

from app.ticketing.services.otp_classifier import classify_otp_email


class TestGenuineOtpEmail:
    def test_task_example_is_classified_as_otp_with_high_confidence(self):
        result = classify_otp_email(
            subject="Your verification code",
            body=(
                "Your one-time verification code is 482931.\n\n"
                "Enter this code to complete your login.\n\n"
                "This code expires in 10 minutes."
            ),
        )

        assert result.is_otp is True
        assert result.confidence >= 0.90

    def test_otp_word_plus_usage_instruction_and_expiration_is_classified_as_otp(self):
        result = classify_otp_email(
            subject="OTP for sign in",
            body=(
                "Your OTP is 738291. Enter this OTP to complete your sign-in. "
                "This OTP is valid for 5 minutes."
            ),
        )

        assert result.is_otp is True

    def test_real_world_otp_email_with_no_expiration_wording_is_classified_as_otp(self):
        # A real inbound OTP email (Hema Healthcare) that has a code
        # noun, a usage instruction, and a real code number, but no
        # "expires in..." wording at all — many real providers omit
        # expiration language entirely. This must still clear the
        # default threshold on code-noun + code-number alone.
        result = classify_otp_email(
            subject="Mail by testing team",
            body=(
                "Hema, please use this one-time code for authentication to "
                "access your hema healthcare account.\n"
                "67896\n"
                "If you have questions or did not request an authentication "
                "code by hema, please contact us at 720753XXXx.\n"
                "This email is sent from an email inbox that is not "
                "monitored. Please do not reply."
            ),
        )

        assert result.is_otp is True
        assert result.confidence >= 0.90


class TestSupportRequestMentioningOtp:
    def test_task_example_is_not_classified_as_otp(self):
        result = classify_otp_email(
            subject="Unable to receive OTP",
            body=(
                "The customer is unable to receive the OTP.\n\n"
                "Please investigate this issue."
            ),
        )

        assert result.is_otp is False
        assert result.confidence <= 0.30

    def test_support_ticket_with_otp_and_code_words_stays_below_threshold(self):
        result = classify_otp_email(
            subject="Issue: verification code not arriving",
            body=(
                "A client reported they did not receive the one-time password. "
                "Please investigate and escalate if needed."
            ),
        )

        assert result.is_otp is False

    def test_internal_ops_message_with_ticket_reference_and_code_number_stays_below_threshold(self):
        # Lowering the bar to "code-noun + a number" (see the two tests
        # above) means an internal ops message that happens to combine
        # "OTP" with an unrelated numeric reference (a ticket/case
        # number, not a customer's own code) must still be rejected.
        result = classify_otp_email(
            subject="Ticket #83920",
            body="Client OTP delivery failed, please check SMTP logs.",
        )

        assert result.is_otp is False


class TestNormalEmails:
    def test_email_with_unrelated_number_is_not_classified_as_otp(self):
        result = classify_otp_email(
            subject="Invoice #4521 for March",
            body="Please find attached invoice number 4521 for the amount due.",
        )

        assert result.is_otp is False

    def test_plain_email_with_no_otp_language_scores_zero(self):
        result = classify_otp_email(
            subject="Question about billing",
            body="Hi, I have a question about my last invoice.",
        )

        assert result.is_otp is False
        assert result.confidence == 0.0

    def test_bare_otp_mention_alone_does_not_clear_default_threshold(self):
        # A single keyword hit (the false-positive case this feature
        # exists to fix) must not be enough on its own.
        result = classify_otp_email(subject="OTP", body="OTP")

        assert result.is_otp is False
        assert result.confidence < 0.90


class TestConfigurableThreshold:
    def test_same_input_classified_differently_at_different_thresholds(self):
        subject = "OTP"
        body = "Your OTP is 123456."

        lenient = classify_otp_email(subject, body, threshold=0.2)
        strict = classify_otp_email(subject, body, threshold=0.99)

        assert lenient.confidence == strict.confidence
        assert lenient.is_otp is True
        assert strict.is_otp is False

    def test_none_subject_and_body_do_not_raise(self):
        result = classify_otp_email(None, None)

        assert result.is_otp is False
        assert result.confidence == 0.0

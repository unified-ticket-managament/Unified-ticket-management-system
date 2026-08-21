"""
Semantic OTP-vs-mention classifier for inbound email subject+body.

Pure, side-effect-free (mirrors rule_conditions.py's "plain data in,
plain bool/score out" convention) — no DB, no I/O, no external NLP/LLM
dependency (none exists in this codebase to reuse). Scores the
combined subject+body text against weighted phrase/pattern categories
that capture genuine one-time-code delivery intent, and applies a hard
confidence ceiling whenever support-request/complaint framing is
present (e.g. "unable to receive the OTP... please investigate") —
the exact false-positive case a "body contains 'OTP'" keyword rule
can't distinguish.

A qualifying code-noun phrase ("OTP", "verification code", "one-time
password", ...) plus an actual code-shaped number in the message are
the two fundamentally defining signals and are, together, sufficient
to clear the default threshold on their own — a genuine code delivery
essentially always carries both, while a complaint about a *missing*
OTP essentially never repeats the customer's own numeric code.
Real-world OTP emails often omit explicit "expires in..." wording
(confirmed against a real inbound OTP email that had no expiration
language at all), so expiration and usage-instruction language are
confirmatory bonus signals, not required components.

The confidence threshold used to derive `is_otp` is a parameter, not
a hardcoded constant — the caller applies its own configured business
threshold (Settings.otp_nlp_confidence_threshold). This module never
decides SLA state; it only classifies text.
"""

from dataclasses import dataclass
import re

DEFAULT_OTP_CONFIDENCE_THRESHOLD = 0.90


@dataclass(frozen=True)
class OTPClassificationResult:
    is_otp: bool
    confidence: float


# A noun phrase naming the thing being delivered — not just the bare
# word "code" in isolation, which says nothing about intent on its own.
_CODE_NOUN_PATTERN = re.compile(
    r"\b("
    r"otp|"
    r"one[- ]?time\s+(?:password|code|pin|passcode)|"
    r"verification\s+code|security\s+code|access\s+code|"
    r"login\s+code|sign[- ]?in\s+code|authentication\s+code|"
    r"passcode|confirmation\s+code|pin\s+code"
    r")\b",
    re.IGNORECASE,
)

# Instructing the reader to actively use a code to complete some
# action right now — the "here is a code, do something with it" shape.
_USAGE_INSTRUCTION_PATTERN = re.compile(
    r"\b(enter|use|input|type)\b[^.\n]{0,25}\b(this|the|your)\b[^.\n]{0,15}\b(code|otp|pin|passcode)\b"
    r"|"
    r"\bto\s+(complete|verify|confirm|finish)\b[^.\n]{0,30}\b(login|log[- ]?in|sign[- ]?in|verification|registration|identity|account)\b",
    re.IGNORECASE,
)

_EXPIRATION_PATTERN = re.compile(
    r"\bexpir(?:e|es|ed|ation|ing)\b|\bvalid\s+(?:for|until)\b",
    re.IGNORECASE,
)

_CODE_SHAPED_NUMBER_PATTERN = re.compile(r"\b\d{4,8}\b")

# Support-request / incident framing — someone describing a problem
# *about* an OTP, not delivering one. A hard override: no amount of
# coincidental keyword overlap elsewhere should push this over the
# confidence threshold.
_SUPPORT_REQUEST_PATTERN = re.compile(
    r"\b("
    r"unable\s+to\s+receive|not\s+receiv(?:e|ing)|"
    r"didn'?t\s+receive|did\s+not\s+receive|failed\s+to\s+receive|"
    r"please\s+(?:investigate|assist|help|look\s+into|check)|"
    r"having\s+(?:trouble|issues?|problems?)|trouble\s+receiving|"
    r"report(?:ed)?\s+(?:an|the)\s+issue|raised\s+a\s+ticket|"
    r"support\s+(?:request|ticket)|kindly\s+(?:assist|check|investigate)|"
    r"escalat(?:e|ion)|complain(?:t)?|"
    r"(?:customer|client|user)\s+(?:is|was|are|were)\s+unable|"
    r"ticket\s*#|case\s*#|ref(?:erence)?\s*#"
    r")\b",
    re.IGNORECASE,
)

_SUPPORT_REQUEST_CONFIDENCE_CEILING = 0.30


def classify_otp_email(
    subject: str | None,
    body: str | None,
    *,
    threshold: float = DEFAULT_OTP_CONFIDENCE_THRESHOLD,
) -> OTPClassificationResult:
    text = f"{subject or ''}\n{body or ''}"

    confidence = 0.0
    if _CODE_NOUN_PATTERN.search(text):
        confidence += 0.55
    if _CODE_SHAPED_NUMBER_PATTERN.search(text):
        confidence += 0.40
    if _USAGE_INSTRUCTION_PATTERN.search(text):
        confidence += 0.20
    if _EXPIRATION_PATTERN.search(text):
        confidence += 0.15

    confidence = min(confidence, 1.0)

    if _SUPPORT_REQUEST_PATTERN.search(text):
        confidence = min(confidence, _SUPPORT_REQUEST_CONFIDENCE_CEILING)

    confidence = round(confidence, 4)

    return OTPClassificationResult(is_otp=confidence >= threshold, confidence=confidence)

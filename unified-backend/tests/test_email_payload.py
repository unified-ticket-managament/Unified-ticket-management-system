# test_email_payload.py
#
# Regression coverage for a real bug: compose_email
# (interaction_service.py) used to store a Compose-authored root's
# HTML under the dict key "body_html", while EmailPayload declared the
# field as `html_body` — open_email_service.py re-parses the stored
# payload through EmailPayload.model_validate, so the mismatched key
# was silently dropped (ConfigDict(extra="ignore")) and
# OpenEmailResponse.body_html came back null even though the real
# sanitized HTML was sitting in the DB. This is why UTMS's own Sent
# view rendered a Compose-authored email's table/image content as
# flattened plain text while the same HTML reached Outlook correctly.
#
# The fix is a validation_alias accepting both keys — this is a
# read-time fix (no backfill needed) covering both already-stored rows
# (the "body_html" key) and new ones (interaction_service.py now
# writes the correctly-named "html_body" key going forward). Pure
# schema-level test, no DB.

from app.ticketing.schemas.payloads.email_payload import EmailPayload


def _base_payload(**overrides: object) -> dict[str, object]:
    return {"subject": "Test subject", "body": "Test body", **overrides}


def test_accepts_the_historical_mismatched_body_html_key():
    payload = EmailPayload.model_validate(_base_payload(body_html="<table><tr><td>a</td></tr></table>"))

    assert payload.html_body == "<table><tr><td>a</td></tr></table>"


def test_accepts_the_correctly_named_html_body_key():
    payload = EmailPayload.model_validate(_base_payload(html_body="<p>hello</p>"))

    assert payload.html_body == "<p>hello</p>"


def test_html_body_defaults_to_none_when_neither_key_is_present():
    payload = EmailPayload.model_validate(_base_payload())

    assert payload.html_body is None


def test_html_body_key_takes_precedence_when_both_are_somehow_present():
    payload = EmailPayload.model_validate(
        _base_payload(html_body="<p>correct</p>", body_html="<p>legacy</p>")
    )

    assert payload.html_body == "<p>correct</p>"


def test_model_dump_round_trips_under_the_real_field_name():
    payload = EmailPayload.model_validate(_base_payload(body_html="<p>x</p>"))

    dumped = payload.model_dump(mode="json")

    assert dumped["html_body"] == "<p>x</p>"
    assert "body_html" not in dumped

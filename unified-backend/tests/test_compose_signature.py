# test_compose_signature.py
#
# Pure-logic coverage for _build_compose_signature (interaction_
# service.py) — the Compose-only signature block appended so a client
# reading a brand-new message (never a Reply, which threads onto a
# conversation already understood to be "the team") can tell which
# agent actually wrote it. No DB: a plain stand-in object is enough,
# since the function only ever reads .name and .role.name.

from types import SimpleNamespace

from app.ticketing.services.interaction_service import _build_compose_signature


def _user(name="Jane Doe", role_name="Account Manager"):
    role = SimpleNamespace(name=role_name) if role_name is not None else None
    return SimpleNamespace(name=name, role=role)


def test_build_compose_signature_includes_name_and_role():
    signature = _build_compose_signature(_user(name="Jane Doe", role_name="Account Manager"))

    assert "Jane Doe" in signature
    assert "Account Manager" in signature
    assert "Probe Practice Solutions" in signature
    assert "Sent via Ticketing Support" in signature
    assert "ticketing@probeps.com" in signature


def test_build_compose_signature_omits_role_line_when_role_is_none():
    signature = _build_compose_signature(_user(name="Jane Doe", role_name=None))

    lines = signature.splitlines()
    assert "Jane Doe" in lines
    # No blank/stray line where the role would have gone — the very
    # next line after the name is the fixed company line, not an
    # empty role.
    name_index = lines.index("Jane Doe")
    assert lines[name_index + 1] == "Probe Practice Solutions"


def test_build_compose_signature_matches_expected_format():
    signature = _build_compose_signature(_user(name="Jane Doe", role_name="Team Lead"))

    assert signature == "\n".join(
        [
            "-" * 40,
            "Regards,",
            "Jane Doe",
            "Team Lead",
            "Probe Practice Solutions",
            "Sent via Ticketing Support",
            "ticketing@probeps.com",
            "-" * 40,
        ]
    )

# test_compose_signature.py
#
# Pure-logic coverage for build_agent_signature (email_envelope.py) —
# the one shared signature block appended across every human-composed
# outbound send path (Compose/Forward via compose_email, Reply via
# add_reply/add_interaction_reply, and transitively Draft-Send via
# add_interaction_reply). No DB: a plain stand-in object is enough,
# since the function only ever reads a handful of plain attributes
# off the User it's given.

from types import SimpleNamespace

from app.ticketing.services.email_envelope import build_agent_signature


def _user(
    name="Jane Doe",
    role_name="Account Manager",
    designation=None,
    department=None,
    phone_number=None,
):
    role = SimpleNamespace(name=role_name) if role_name is not None else None
    return SimpleNamespace(
        name=name,
        role=role,
        designation=designation,
        department=department,
        phone_number=phone_number,
    )


def test_build_agent_signature_falls_back_to_role_when_no_designation():
    signature = build_agent_signature(
        _user(name="Jane Doe", role_name="Account Manager", designation=None)
    )

    assert "Jane Doe" in signature
    assert "Account Manager" in signature
    assert "Probe Practice Solutions" in signature


def test_build_agent_signature_prefers_designation_over_role():
    signature = build_agent_signature(
        _user(name="Jane Doe", role_name="Account Manager", designation="Sr. AR Associate")
    )

    assert "Sr. AR Associate" in signature
    # The RBAC role name itself shouldn't appear when a real
    # designation is present — designation is preferred, not merely
    # appended alongside it.
    assert "Account Manager" not in signature


def test_build_agent_signature_never_hardcodes_a_mailbox_address():
    signature = build_agent_signature(_user())

    # The signature identifies the employee, never the sending
    # mailbox (that's resolved separately, per-message, and can be
    # the shared inbox or a client-specific one) — asserting the old
    # hardcoded literal is gone is the regression this guards against.
    assert "ticketing@probeps.com" not in signature
    assert "@" not in signature


def test_build_agent_signature_omits_optional_fields_when_unset():
    signature = build_agent_signature(
        _user(name="Jane Doe", role_name=None, designation=None, department=None, phone_number=None)
    )

    lines = signature.splitlines()
    assert "Jane Doe" in lines
    # No blank/stray line where title/department/phone would have
    # gone — the very next line after the name is the fixed company
    # line, not an empty field.
    name_index = lines.index("Jane Doe")
    assert lines[name_index + 1] == "Probe Practice Solutions"


def test_build_agent_signature_includes_department_and_phone_when_set():
    signature = build_agent_signature(
        _user(
            name="Jane Doe",
            role_name="Team Lead",
            designation="Team Lead - AR",
            department="Accounts Receivable",
            phone_number="+1-555-0100",
        )
    )

    assert signature == "\n".join(
        [
            "-" * 40,
            "Regards,",
            "Jane Doe",
            "Team Lead - AR",
            "Probe Practice Solutions",
            "Accounts Receivable",
            "+1-555-0100",
            "-" * 40,
        ]
    )

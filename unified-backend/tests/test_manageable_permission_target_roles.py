# test_manageable_permission_target_roles.py
#
# Coverage for the fix to
# access_control.get_manageable_permission_target_role_names /
# ensure_can_manage_role_permissions:
#
#   MANAGEABLE_PERMISSION_TARGET_ROLES.get(actor.role.name) used to
#   return None both for the dict's own explicit `"Super Admin": None`
#   (meant as "unrestricted") AND for any role with no entry at all
#   (meant as "can never manage any role's permissions") — the two
#   cases were indistinguishable to the caller, so a role missing from
#   the map was silently treated as unrestricted instead of denied.
#   Fixed with an explicit membership check, mirroring the sibling
#   USER_CREATION_ROLE_MATRIX's already-correct `.get(name, set())`
#   convention in the same file.
#
# Pure-logic, no DB — mirrors test_user_creation_role_matrix.py's own
# `ensure_can_create_role` section, which tests this exact idiom for
# its sibling matrix the same way.

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.rbac.services import access_control


def _actor(role_name: str):
    return SimpleNamespace(role=SimpleNamespace(name=role_name))


def _role(role_name: str):
    return SimpleNamespace(name=role_name)


@pytest.mark.parametrize(
    "target_role_name",
    ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff", "Client"],
)
def test_super_admin_is_unrestricted(target_role_name):
    assert access_control.get_manageable_permission_target_role_names(_actor("Super Admin")) is None
    # Must not raise for any target role.
    access_control.ensure_can_manage_role_permissions(_actor("Super Admin"), _role(target_role_name))


def test_site_lead_is_restricted_to_its_existing_set():
    allowed = access_control.get_manageable_permission_target_role_names(_actor("Site Lead"))
    assert allowed == {"Account Manager", "Team Lead", "Staff"}

    for target_role_name in allowed:
        access_control.ensure_can_manage_role_permissions(_actor("Site Lead"), _role(target_role_name))

    with pytest.raises(HTTPException) as exc_info:
        access_control.ensure_can_manage_role_permissions(_actor("Site Lead"), _role("Super Admin"))
    assert exc_info.value.status_code == 403


def test_account_manager_is_restricted_to_its_existing_set():
    allowed = access_control.get_manageable_permission_target_role_names(_actor("Account Manager"))
    assert allowed == {"Team Lead", "Staff"}

    for target_role_name in allowed:
        access_control.ensure_can_manage_role_permissions(
            _actor("Account Manager"), _role(target_role_name)
        )

    with pytest.raises(HTTPException) as exc_info:
        access_control.ensure_can_manage_role_permissions(
            _actor("Account Manager"), _role("Site Lead")
        )
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize(
    "actor_role_name",
    ["Team Lead", "Staff", "Client", "Some Future Role With No Entry"],
)
@pytest.mark.parametrize(
    "target_role_name",
    ["Super Admin", "Site Lead", "Account Manager", "Team Lead", "Staff", "Client"],
)
def test_role_missing_from_matrix_is_denied_never_unrestricted(actor_role_name, target_role_name):
    """
    The actual bug this fix closes: before the fix, `.get(name)` on a
    missing key returned None — read by the caller as "unrestricted" —
    identically to Super Admin's own explicit None entry. Every one of
    these actor/target combinations must now be denied.
    """

    assert access_control.get_manageable_permission_target_role_names(_actor(actor_role_name)) == set()

    with pytest.raises(HTTPException) as exc_info:
        access_control.ensure_can_manage_role_permissions(
            _actor(actor_role_name), _role(target_role_name)
        )
    assert exc_info.value.status_code == 403

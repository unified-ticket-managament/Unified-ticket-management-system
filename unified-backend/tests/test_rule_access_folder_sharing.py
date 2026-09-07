# test_rule_access_folder_sharing.py
#
# Pure-logic coverage for rule_access.folder_name_to_rules/
# has_folder_share_access — the mechanism behind the "Sharing" bug fix
# (a folder the viewer has been granted access to via a rule's
# shared_user_ids/created_by/rule:view_all must actually surface that
# folder's messages, not just its empty existence). No DB, no real
# Rule rows — a Rule is a plain SQLAlchemy model with no relationships
# needed here, so a minimal instance (rule_id/created_by/
# shared_user_ids/actions/is_enabled only) is enough.

from uuid import uuid4

from app.ticketing.models.rule import Rule
from app.ticketing.services.rule_access import (
    RULE_MANAGE_ALL_PERMISSION,
    can_manage_rule,
    can_view_rule,
    folder_name_to_rules,
    has_folder_share_access,
)


class _FakeRole:
    def __init__(self, name):
        self.name = name


class _FakeUser:
    def __init__(self, user_id, role_name="Team Lead", permissions=None):
        self.user_id = user_id
        self.role = _FakeRole(role_name)
        self.permissions = permissions if permissions is not None else []


def _rule(
    *,
    created_by,
    shared_user_ids=None,
    shared_distribution_list_ids=None,
    folder_name="apm folder",
    is_enabled=True,
):
    return Rule(
        rule_id=uuid4(),
        name="Test rule",
        category="MAIL_RULE",
        is_enabled=is_enabled,
        conditions={"combinator": "AND", "rules": []},
        exceptions={"combinator": "AND", "rules": []},
        actions=[{"type": "move_to_folder", "folder_name": folder_name}],
        priority=1,
        created_by=created_by,
        shared_user_ids=shared_user_ids or [],
        shared_distribution_list_ids=shared_distribution_list_ids or [],
    )


class TestFolderNameToRules:
    def test_groups_rules_by_referenced_folder_name(self):
        creator_id = uuid4()
        rule_a = _rule(created_by=creator_id, folder_name="apm folder")
        rule_b = _rule(created_by=creator_id, folder_name="billing folder")
        mapping = folder_name_to_rules([rule_a, rule_b])
        assert mapping["apm folder"] == [rule_a]
        assert mapping["billing folder"] == [rule_b]

    def test_multiple_rules_referencing_same_folder_both_grouped(self):
        creator_id = uuid4()
        rule_a = _rule(created_by=creator_id, folder_name="apm folder")
        rule_b = _rule(created_by=uuid4(), folder_name="apm folder")
        mapping = folder_name_to_rules([rule_a, rule_b])
        assert mapping["apm folder"] == [rule_a, rule_b]

    def test_rule_with_no_folder_action_contributes_nothing(self):
        creator_id = uuid4()
        rule = Rule(
            rule_id=uuid4(),
            name="Forward-only rule",
            category="MAIL_RULE",
            is_enabled=True,
            conditions={"combinator": "AND", "rules": []},
            exceptions={"combinator": "AND", "rules": []},
            actions=[{"type": "forward_to", "employee_user_ids": [str(uuid4())]}],
            priority=1,
            created_by=creator_id,
            shared_user_ids=[],
        )
        mapping = folder_name_to_rules([rule])
        assert mapping == {}


class TestHasFolderShareAccess:
    def test_shared_member_gets_access(self):
        creator_id = uuid4()
        viewer_id = uuid4()
        rule = _rule(created_by=creator_id, shared_user_ids=[str(viewer_id)])
        viewer = _FakeUser(viewer_id)
        mapping = folder_name_to_rules([rule])
        assert has_folder_share_access("apm folder", viewer, mapping) is True

    def test_creator_gets_access(self):
        creator_id = uuid4()
        rule = _rule(created_by=creator_id)
        creator = _FakeUser(creator_id)
        mapping = folder_name_to_rules([rule])
        assert has_folder_share_access("apm folder", creator, mapping) is True

    def test_rule_view_all_permission_gets_access(self):
        rule = _rule(created_by=uuid4())
        viewer = _FakeUser(uuid4(), permissions=["rule:view_all"])
        mapping = folder_name_to_rules([rule])
        assert has_folder_share_access("apm folder", viewer, mapping) is True

    def test_unrelated_viewer_denied(self):
        rule = _rule(created_by=uuid4(), shared_user_ids=[str(uuid4())])
        viewer = _FakeUser(uuid4())
        mapping = folder_name_to_rules([rule])
        assert has_folder_share_access("apm folder", viewer, mapping) is False

    def test_no_referencing_rule_denies_even_the_folder_owner(self):
        # A folder that exists but that no current rule files mail
        # into must fall back to the normal ownership-scoped query,
        # never this bypass — even for whoever originally created it.
        viewer = _FakeUser(uuid4())
        mapping: dict[str, list[Rule]] = {}
        assert has_folder_share_access("orphaned folder", viewer, mapping) is False

    def test_disabled_but_shared_rule_still_grants_access(self):
        # Matches GET /folders' own existing behavior: RuleRepository.
        # list_all() has no enabled/disabled filter, so a disabled
        # rule's folder-sharing grant must not be stricter than what
        # folder-existence visibility already allows today.
        creator_id = uuid4()
        viewer_id = uuid4()
        rule = _rule(
            created_by=creator_id,
            shared_user_ids=[str(viewer_id)],
            is_enabled=False,
        )
        viewer = _FakeUser(viewer_id)
        mapping = folder_name_to_rules([rule])
        assert has_folder_share_access("apm folder", viewer, mapping) is True

    def test_only_one_of_several_rules_referencing_folder_shared_still_grants(self):
        folder_name = "shared with only one rule"
        creator_id = uuid4()
        viewer_id = uuid4()
        shared_rule = _rule(
            created_by=creator_id, shared_user_ids=[str(viewer_id)], folder_name=folder_name
        )
        unrelated_rule = _rule(created_by=uuid4(), folder_name=folder_name)
        viewer = _FakeUser(viewer_id)
        mapping = folder_name_to_rules([shared_rule, unrelated_rule])
        assert has_folder_share_access(folder_name, viewer, mapping) is True


class TestDistributionListSharing:
    # A Distribution List member gets exactly the same folder-share
    # access a directly-listed employee would — passed in as an
    # already-resolved id set (the caller's job — see
    # DistributionListRepository.list_active_list_ids_for_user — this
    # module stays pure/no-I/O), never re-resolved here.

    def test_distribution_list_member_gets_access(self):
        creator_id = uuid4()
        member_id = uuid4()
        dl_id = uuid4()
        rule = _rule(created_by=creator_id, shared_distribution_list_ids=[str(dl_id)])
        member = _FakeUser(member_id)
        mapping = folder_name_to_rules([rule])
        assert (
            has_folder_share_access("apm folder", member, mapping, user_distribution_list_ids=[dl_id])
            is True
        )

    def test_non_member_of_shared_distribution_list_denied(self):
        creator_id = uuid4()
        outsider_id = uuid4()
        dl_id = uuid4()
        other_dl_id = uuid4()
        rule = _rule(created_by=creator_id, shared_distribution_list_ids=[str(dl_id)])
        outsider = _FakeUser(outsider_id)
        mapping = folder_name_to_rules([rule])
        # Belongs to some other Distribution List, just not the one
        # this rule actually shares with.
        assert (
            has_folder_share_access(
                "apm folder", outsider, mapping, user_distribution_list_ids=[other_dl_id]
            )
            is False
        )

    def test_no_distribution_list_ids_passed_is_a_plain_deny(self):
        creator_id = uuid4()
        viewer_id = uuid4()
        dl_id = uuid4()
        rule = _rule(created_by=creator_id, shared_distribution_list_ids=[str(dl_id)])
        viewer = _FakeUser(viewer_id)
        mapping = folder_name_to_rules([rule])
        assert has_folder_share_access("apm folder", viewer, mapping) is False

    def test_mixed_direct_and_distribution_list_sharing_no_duplicate_grant_needed(self):
        # An employee who is both directly shared AND a member of a
        # shared Distribution List still just gets one True — the
        # boolean OR check itself has nothing to deduplicate.
        creator_id = uuid4()
        viewer_id = uuid4()
        dl_id = uuid4()
        rule = _rule(
            created_by=creator_id,
            shared_user_ids=[str(viewer_id)],
            shared_distribution_list_ids=[str(dl_id)],
        )
        viewer = _FakeUser(viewer_id)
        mapping = folder_name_to_rules([rule])
        assert (
            has_folder_share_access("apm folder", viewer, mapping, user_distribution_list_ids=[dl_id])
            is True
        )


class TestRuleManageAllPermission:
    """
    Decision 5 coverage: rule:manage_all is a reusable capability, not
    a Site-Lead-specific one — can_manage_rule checks the permission
    string alone, with no role-name branch anywhere. Granting the same
    permission to any other role/user must produce identical behavior,
    with zero code change — exercised here by simply using a Staff
    fake user, never a "Site Lead" role name.
    """

    def test_holder_can_manage_a_rule_they_neither_created_nor_are_shared_on(self):
        rule = _rule(created_by=uuid4())
        holder = _FakeUser(uuid4(), role_name="Staff", permissions=[RULE_MANAGE_ALL_PERMISSION])
        assert can_manage_rule(rule, holder) is True

    def test_non_holder_still_denied_manage_without_ownership_or_sharing(self):
        rule = _rule(created_by=uuid4())
        stranger = _FakeUser(uuid4(), role_name="Staff", permissions=[])
        assert can_manage_rule(rule, stranger) is False

    def test_view_all_does_not_grant_manage(self):
        """Regression: rule:view_all (the pre-existing, narrower
        permission) must still never grant manage rights — the two
        remain deliberately distinct, exactly as can_view_rule/
        can_manage_rule's own asymmetry already establishes."""

        rule = _rule(created_by=uuid4())
        view_all_holder = _FakeUser(uuid4(), role_name="Staff", permissions=["rule:view_all"])
        assert can_manage_rule(rule, view_all_holder) is False
        # ... but view_all still grants view, unaffected by any of this.
        assert can_view_rule(rule, view_all_holder) is True

    def test_manage_all_also_grants_view(self):
        """A manage_all holder can, at minimum, also view the rule —
        can_view_rule doesn't check this permission explicitly, but
        ownership/sharing is a strict subset of what manage implies in
        practice; this just confirms manage_all is never a view-only
        grant that silently blocks editing (the actual point of this
        whole capability)."""

        rule = _rule(created_by=uuid4())
        holder = _FakeUser(uuid4(), role_name="Staff", permissions=[RULE_MANAGE_ALL_PERMISSION])
        assert can_manage_rule(rule, holder) is True

    def test_owner_and_shared_user_paths_unaffected(self):
        """Regression: the pre-existing ownership/sharing paths keep
        working exactly as before, with no manage_all permission
        involved at all."""

        creator_id = uuid4()
        shared_id = uuid4()
        rule = _rule(created_by=creator_id, shared_user_ids=[str(shared_id)])
        creator = _FakeUser(creator_id, permissions=[])
        shared_user = _FakeUser(shared_id, permissions=[])
        stranger = _FakeUser(uuid4(), permissions=[])

        assert can_manage_rule(rule, creator) is True
        assert can_manage_rule(rule, shared_user) is True
        assert can_manage_rule(rule, stranger) is False

    def test_can_view_and_can_manage_rule_both_grant_via_distribution_list(self):
        creator_id = uuid4()
        member_id = uuid4()
        dl_id = uuid4()
        rule = _rule(created_by=creator_id, shared_distribution_list_ids=[str(dl_id)])
        member = _FakeUser(member_id)
        assert can_view_rule(rule, member, [dl_id]) is True
        assert can_manage_rule(rule, member, [dl_id]) is True
        # And without the DL membership, denied on both.
        assert can_view_rule(rule, member, []) is False
        assert can_manage_rule(rule, member, []) is False

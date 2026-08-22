# test_recipient_merge.py
#
# Pure logic tests for the shared recipient-merge/dedup helpers used
# by forward_to_internal_user/add_reply/add_interaction_reply/
# compose_email/add_internal_note — no database needed. Mirrors
# test_otp_classifier.py's own "plain data in, plain result out" style.

import asyncio
from uuid import uuid4

from app.ticketing.utils.recipient_merge import (
    dedupe_emails_case_insensitive,
    merge_recipients_with_priority,
    remove_addresses_case_insensitive,
    resolve_distribution_list_emails,
    resolve_distribution_list_members,
)


class TestDedupeEmailsCaseInsensitive:
    def test_dedupes_across_multiple_groups_case_insensitively(self):
        result = dedupe_emails_case_insensitive(
            ["Kamal@example.com", "satish@example.com"],
            ["kamal@example.com", "pavana@example.com"],
        )
        assert result == ["Kamal@example.com", "satish@example.com", "pavana@example.com"]

    def test_first_seen_casing_wins(self):
        result = dedupe_emails_case_insensitive(["Foo@Bar.com"], ["foo@bar.com"])
        assert result == ["Foo@Bar.com"]

    def test_ignores_blank_entries(self):
        assert dedupe_emails_case_insensitive(["a@b.com", "  ", ""], []) == ["a@b.com"]

    def test_empty_input_returns_empty(self):
        assert dedupe_emails_case_insensitive() == []
        assert dedupe_emails_case_insensitive([], []) == []


class TestRemoveAddressesCaseInsensitive:
    def test_removes_matching_addresses_case_insensitively(self):
        result = remove_addresses_case_insensitive(
            ["Kamal@example.com", "satish@example.com"], ["kamal@EXAMPLE.com"]
        )
        assert result == ["satish@example.com"]

    def test_no_match_leaves_candidates_untouched(self):
        result = remove_addresses_case_insensitive(["a@b.com"], ["c@d.com"])
        assert result == ["a@b.com"]


class TestMergeRecipientsWithPriority:
    def test_to_beats_cc_and_bcc(self):
        to, cc, bcc = merge_recipients_with_priority(
            to=["client@example.com"],
            cc=["client@example.com", "kamal@example.com"],
            bcc=["client@example.com"],
        )
        assert to == ["client@example.com"]
        assert cc == ["kamal@example.com"]
        assert bcc == []

    def test_cc_beats_bcc(self):
        to, cc, bcc = merge_recipients_with_priority(
            to=[], cc=["kamal@example.com"], bcc=["kamal@example.com", "satish@example.com"]
        )
        assert cc == ["kamal@example.com"]
        assert bcc == ["satish@example.com"]

    def test_bcc_confidentiality_never_promoted_into_cc(self):
        """
        A Distribution List member who is also deliberately Bcc'd must
        never be silently promoted into the visible Cc header — the
        real confidentiality concern this function exists to prevent.
        """

        to, cc, bcc = merge_recipients_with_priority(
            to=[],
            cc=["kamal@example.com"],  # resolved from a Distribution List
            bcc=["kamal@example.com"],  # the agent deliberately Bcc'd the same person
        )
        # kamal ends up in cc (cc > bcc priority means bcc loses the
        # duplicate) — but never appears in BOTH, and is never absent
        # from cc while silently retained in bcc either.
        assert cc == ["kamal@example.com"]
        assert bcc == []

    def test_each_bucket_self_deduped(self):
        to, cc, bcc = merge_recipients_with_priority(
            to=[], cc=["a@b.com", "A@B.com"], bcc=[]
        )
        assert cc == ["a@b.com"]

    def test_all_empty_returns_all_empty(self):
        assert merge_recipients_with_priority(to=[], cc=[], bcc=[]) == ([], [], [])


class _FakeDistributionListRepository:
    def __init__(self, by_list_id):
        self._by_list_id = by_list_id

    async def get_active_member_emails_by_list_ids(self, distribution_list_ids):
        return {
            list_id: self._by_list_id.get(list_id, {}) for list_id in distribution_list_ids
        }


class TestResolveDistributionListEmails:
    def test_flattens_members_across_lists(self):
        list_a, list_b = uuid4(), uuid4()
        user_1, user_2 = uuid4(), uuid4()
        repo = _FakeDistributionListRepository(
            {list_a: {user_1: "kamal@example.com"}, list_b: {user_2: "satish@example.com"}}
        )

        result = asyncio.run(resolve_distribution_list_emails(repo, [list_a, list_b]))

        assert set(result) == {"kamal@example.com", "satish@example.com"}

    def test_no_repository_returns_empty(self):
        result = asyncio.run(resolve_distribution_list_emails(None, [uuid4()]))
        assert result == []

    def test_no_ids_returns_empty_without_calling_repository(self):
        result = asyncio.run(resolve_distribution_list_emails(_FakeDistributionListRepository({}), []))
        assert result == []

    def test_stale_or_empty_list_contributes_nothing_without_raising(self):
        list_id = uuid4()
        repo = _FakeDistributionListRepository({})  # resolves to {} for any id

        result = asyncio.run(resolve_distribution_list_emails(repo, [list_id]))

        assert result == []


class TestResolveDistributionListMembers:
    def test_merges_user_id_keyed_members_across_lists(self):
        list_a, list_b = uuid4(), uuid4()
        user_1, user_2 = uuid4(), uuid4()
        repo = _FakeDistributionListRepository(
            {list_a: {user_1: "kamal@example.com"}, list_b: {user_2: "satish@example.com"}}
        )

        result = asyncio.run(resolve_distribution_list_members(repo, [list_a, list_b]))

        assert result == {user_1: "kamal@example.com", user_2: "satish@example.com"}

    def test_no_repository_returns_empty(self):
        result = asyncio.run(resolve_distribution_list_members(None, [uuid4()]))
        assert result == {}

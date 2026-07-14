# test_escalation_rules.py
#
# Pure, no-DB tests for the internal escalation ownership chain — same
# style as test_sla_escalation_rules.py (resolvers only ever read
# already-loaded Python attributes, so plain unpersisted User
# instances are enough).

import uuid

from shared_models.models import User

from app.ticketing.enums import EscalationLevel
from app.ticketing.services.escalation_rules import (
    ESCALATION_LEVEL_ORDER,
    next_level,
    resolve_manager_ids,
)


def _user(manager_id=None) -> User:
    return User(user_id=uuid.uuid4(), manager_id=manager_id)


class TestNextLevel:
    def test_no_escalation_yet_starts_at_team_lead(self):
        assert next_level(None) == EscalationLevel.TEAM_LEAD

    def test_team_lead_advances_to_manager(self):
        assert next_level(EscalationLevel.TEAM_LEAD) == EscalationLevel.MANAGER

    def test_manager_advances_to_site_lead(self):
        assert next_level(EscalationLevel.MANAGER) == EscalationLevel.SITE_LEAD

    def test_site_lead_is_terminal(self):
        assert next_level(EscalationLevel.SITE_LEAD) is None

    def test_order_matches_the_documented_chain(self):
        assert ESCALATION_LEVEL_ORDER == (
            EscalationLevel.TEAM_LEAD,
            EscalationLevel.MANAGER,
            EscalationLevel.SITE_LEAD,
        )


class TestResolveManagerIds:
    def test_no_users_resolves_to_nobody(self):
        assert resolve_manager_ids([]) == set()

    def test_user_with_no_manager_resolves_to_nobody(self):
        assert resolve_manager_ids([_user(manager_id=None)]) == set()

    def test_resolves_each_distinct_manager(self):
        m1, m2 = uuid.uuid4(), uuid.uuid4()
        users = [_user(manager_id=m1), _user(manager_id=m2)]
        assert resolve_manager_ids(users) == {m1, m2}

    def test_shared_manager_is_deduplicated(self):
        shared_manager = uuid.uuid4()
        users = [_user(manager_id=shared_manager), _user(manager_id=shared_manager)]
        assert resolve_manager_ids(users) == {shared_manager}

    def test_mixed_managers_and_none_only_resolves_the_present_ones(self):
        m1 = uuid.uuid4()
        users = [_user(manager_id=m1), _user(manager_id=None)]
        assert resolve_manager_ids(users) == {m1}

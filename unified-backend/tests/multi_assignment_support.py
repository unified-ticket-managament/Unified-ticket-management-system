"""
Shared fixtures for the multi-user / multi-category assignment suites
(test_multi_assignment.py, test_multi_assignment_api_e2e.py).

Everything is created inside ONE session whose transaction is always
rolled back — same convention as the rest of this suite against the
shared dev database. Unlike older suites, the world (roles are looked
up; categories, users, client, ticket are created fresh) is fully
self-contained, so these tests never depend on drifting seed data.

Permissions are set explicitly per user (mirroring seed.py's role
defaults) so RBAC behavior under test is deterministic — exactly what
get_current_user would attach from the JWT.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from shared_models.models import Category, Role, User

from app.ticketing.enums import TicketPriority, TicketStatus
from app.ticketing.models.client import Client
from app.ticketing.models.ticket import Ticket
from app.ticketing.repositories.client_repository import ClientRepository
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.ticket_repository import TicketRepository
from app.ticketing.repositories.user_repository import UserRepository
from app.ticketing.services.escalation_service import build_escalation_service
from app.ticketing.services.interaction_service import InteractionService
from app.ticketing.services.sla_service import build_sla_service
from app.ticketing.services.ticket_assignment_service import build_ticket_assignment_service

STAFF_PERMISSIONS = [
    "ticket:view_own",
    "ticket:view_unassigned",
    "ticket:view_others",
    "ticket:update_status",
    "ticket:reply",
    "ticket:upload_attachment",
    "ticket:editown_ticket",
    "ticket:view_escalated",
]
TEAM_LEAD_PERMISSIONS = STAFF_PERMISSIONS + [
    "ticket:assign",
    "ticket:transfer",
    "ticket:editother_ticket",
]
ACCOUNT_MANAGER_PERMISSIONS = TEAM_LEAD_PERMISSIONS + [
    "ticket:change_category",
    "ticket:create",
    "ticket:close_ticket",
    "ticket:reopen",
    "ticket:change_priority",
]


@dataclass
class World:
    session: object
    tag: str
    billing: Category
    claims: Category
    denials: Category
    account_manager: User
    other_account_manager: User
    team_lead: User
    site_lead: User
    koushik: User
    ravi: User
    suresh: User
    outsider: User
    client: Client
    users: dict = field(default_factory=dict)


async def _role(session, name: str) -> Role:
    role = (await session.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    assert role is not None, f"Role {name!r} must exist in the connected database."
    return role


def _make_user(session, *, name, role, tag, categories=(), permissions=(), manager_id=None):
    user = User(
        user_id=uuid.uuid4(),
        name=name,
        email=f"{name.lower().replace(' ', '.')}.{tag}@multi-assign.test",
        password_hash="not-a-real-hash",
        role_id=role.role_id,
        is_active=True,
        manager_id=manager_id,
    )
    user.role = role
    user.categories = list(categories)
    session.add(user)
    user.permissions = list(permissions)
    user.scoped_permissions = {}
    return user


async def build_world(session) -> World:
    tag = uuid.uuid4().hex[:8]
    staff_role = await _role(session, "Staff")
    team_lead_role = await _role(session, "Team Lead")
    account_manager_role = await _role(session, "Account Manager")
    site_lead_role = await _role(session, "Site Lead")

    billing = Category(category_id=uuid.uuid4(), category_name=f"Medical Billing {tag}")
    claims = Category(category_id=uuid.uuid4(), category_name=f"Claims {tag}")
    denials = Category(category_id=uuid.uuid4(), category_name=f"Denials {tag}")
    session.add_all([billing, claims, denials])
    await session.flush()

    account_manager = _make_user(session, name="AM", role=account_manager_role, tag=tag, permissions=ACCOUNT_MANAGER_PERMISSIONS)
    other_account_manager = _make_user(session, name="Other AM", role=account_manager_role, tag=tag, permissions=ACCOUNT_MANAGER_PERMISSIONS)
    site_lead = _make_user(session, name="Site Lead", role=site_lead_role, tag=tag, permissions=ACCOUNT_MANAGER_PERMISSIONS)
    team_lead = _make_user(session, name="Team Lead", role=team_lead_role, tag=tag, categories=[billing, claims], permissions=TEAM_LEAD_PERMISSIONS)
    koushik = _make_user(session, name="Koushik", role=staff_role, tag=tag, categories=[billing], permissions=STAFF_PERMISSIONS)
    ravi = _make_user(session, name="Ravi", role=staff_role, tag=tag, categories=[billing], permissions=STAFF_PERMISSIONS)
    suresh = _make_user(session, name="Suresh", role=staff_role, tag=tag, categories=[claims], permissions=STAFF_PERMISSIONS)
    outsider = _make_user(session, name="Outsider", role=staff_role, tag=tag, categories=[denials], permissions=STAFF_PERMISSIONS)
    await session.flush()

    client = Client(
        client_id=uuid.uuid4(),
        name=f"Multi-assign Client {tag}",
        inbox_email=f"multi-assign-{tag}@example.com",
        account_manager_id=account_manager.user_id,
        is_active=True,
    )
    session.add(client)
    await session.flush()

    world = World(
        session=session,
        tag=tag,
        billing=billing,
        claims=claims,
        denials=denials,
        account_manager=account_manager,
        other_account_manager=other_account_manager,
        team_lead=team_lead,
        site_lead=site_lead,
        koushik=koushik,
        ravi=ravi,
        suresh=suresh,
        outsider=outsider,
        client=client,
    )
    world.users = {
        u.name: u
        for u in (account_manager, other_account_manager, site_lead, team_lead, koushik, ravi, suresh, outsider)
    }
    return world


async def make_ticket(world: World, *, categories=None, agent: User | None = None, status=TicketStatus.OPEN) -> Ticket:
    """
    A ticket shaped exactly like a real one created through the inbox:
    ticket-level Resolution SLA started, primary category projected,
    and (optionally) a primary assignee — via the same hooks
    InboxTicketService.create_ticket_from_interaction calls.
    """

    session = world.session
    categories = categories or [world.billing]
    ticket = Ticket(
        ticket_id=uuid.uuid4(),
        client_company_id=world.client.client_id,
        agent_id=agent.user_id if agent else None,
        assigned_by=world.account_manager.user_id if agent else None,
        created_by=world.account_manager.user_id,
        title=f"Multi-assign ticket {world.tag}",
        ticket_type=categories[0].category_name,
        current_status=status,
        current_priority=TicketPriority.MEDIUM,
        created_at=datetime.now(timezone.utc),
    )
    session.add(ticket)
    await session.flush()
    await build_sla_service(session).start_resolution_clock(
        ticket_id=ticket.ticket_id,
        client_id=ticket.client_company_id,
        priority=ticket.current_priority,
    )
    service = build_ticket_assignment_service(session)
    await service.on_ticket_created(ticket, actor_id=world.account_manager.user_id)
    for extra in categories[1:]:
        await service.add_category(ticket.ticket_id, extra.category_id, world.account_manager)
    return ticket


def interaction_service(session, *, notification_service=None) -> InteractionService:
    return InteractionService(
        interaction_repository=InteractionRepository(session),
        ticket_repository=TicketRepository(session),
        user_repository=UserRepository(session),
        client_repository=ClientRepository(session),
        sla_service=build_sla_service(session),
        escalation_service=build_escalation_service(session),
        notification_service=notification_service,
    )

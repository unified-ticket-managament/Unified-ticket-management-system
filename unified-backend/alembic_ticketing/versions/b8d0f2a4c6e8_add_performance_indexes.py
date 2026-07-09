"""add performance indexes to interactions/tickets/clients

Revision ID: b8d0f2a4c6e8
Revises: 34c63a9d3ef2
Create Date: 2026-07-09 00:00:00.000000

None of these columns were indexed despite being exactly what every
list/filter query in this service runs through: the inbox views filter
on interactions.status/is_visible/interaction_type/claimed_by/
folder_id/snoozed_until and join through client_id/ticket_id/
parent_interaction_id; the tickets list filters/scopes on agent_id/
client_company_id/ticket_type/current_status; client ownership scoping
filters on clients.account_manager_id. Purely additive B-tree indexes,
no data changes, safe to run against the live DB with no downtime.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d0f2a4c6e8'
down_revision: Union[str, None] = '34c63a9d3ef2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_interactions_ticket_id", "interactions", ["ticket_id"])
    op.create_index("ix_interactions_parent_interaction_id", "interactions", ["parent_interaction_id"])
    op.create_index("ix_interactions_client_id", "interactions", ["client_id"])
    op.create_index("ix_interactions_status", "interactions", ["status"])
    op.create_index("ix_interactions_is_visible", "interactions", ["is_visible"])
    op.create_index("ix_interactions_interaction_type", "interactions", ["interaction_type"])
    op.create_index("ix_interactions_performed_by", "interactions", ["performed_by"])
    op.create_index("ix_interactions_claimed_by", "interactions", ["claimed_by"])
    op.create_index("ix_interactions_folder_id", "interactions", ["folder_id"])
    op.create_index("ix_interactions_snoozed_until", "interactions", ["snoozed_until"])
    op.create_index("ix_interactions_created_at", "interactions", ["created_at"])
    op.create_index("ix_interactions_received_at", "interactions", ["received_at"])

    op.create_index("ix_tickets_agent_id", "tickets", ["agent_id"])
    op.create_index("ix_tickets_client_company_id", "tickets", ["client_company_id"])
    op.create_index("ix_tickets_ticket_type", "tickets", ["ticket_type"])
    op.create_index("ix_tickets_current_status", "tickets", ["current_status"])
    op.create_index("ix_tickets_created_at", "tickets", ["created_at"])

    op.create_index("ix_clients_account_manager_id", "clients", ["account_manager_id"])


def downgrade() -> None:
    op.drop_index("ix_clients_account_manager_id", table_name="clients")

    op.drop_index("ix_tickets_created_at", table_name="tickets")
    op.drop_index("ix_tickets_current_status", table_name="tickets")
    op.drop_index("ix_tickets_ticket_type", table_name="tickets")
    op.drop_index("ix_tickets_client_company_id", table_name="tickets")
    op.drop_index("ix_tickets_agent_id", table_name="tickets")

    op.drop_index("ix_interactions_received_at", table_name="interactions")
    op.drop_index("ix_interactions_created_at", table_name="interactions")
    op.drop_index("ix_interactions_snoozed_until", table_name="interactions")
    op.drop_index("ix_interactions_folder_id", table_name="interactions")
    op.drop_index("ix_interactions_claimed_by", table_name="interactions")
    op.drop_index("ix_interactions_performed_by", table_name="interactions")
    op.drop_index("ix_interactions_interaction_type", table_name="interactions")
    op.drop_index("ix_interactions_is_visible", table_name="interactions")
    op.drop_index("ix_interactions_status", table_name="interactions")
    op.drop_index("ix_interactions_client_id", table_name="interactions")
    op.drop_index("ix_interactions_parent_interaction_id", table_name="interactions")
    op.drop_index("ix_interactions_ticket_id", table_name="interactions")

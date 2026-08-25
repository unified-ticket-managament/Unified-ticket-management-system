# mail_integrity.py
#
# Phase 2 hardening: distinguishes the one specific benign race a
# concurrent inbound-mail insert can hit (two workers/transports —
# poller and webhook, or two overlapping poll ticks — both trying to
# store the same message at once; the loser hits Interaction.message_id's
# unique constraint) from a genuine processing failure. Kept separate
# from graph_retry.py, which is an unrelated Graph-HTTP-retry wrapper.

from sqlalchemy.exc import IntegrityError

# Postgres's own default naming for an unnamed
# sa.UniqueConstraint('message_id') (see the initial migration,
# c6f212b05143_initial_ticket_management_schema.py) — confirmed via
# that migration's own `sa.UniqueConstraint('message_id')` on the
# `interactions` table, which Postgres names `<table>_<column>_key`.
MESSAGE_ID_UNIQUE_CONSTRAINT_NAME = "interactions_message_id_key"


def is_duplicate_message_id_violation(exc: Exception) -> bool:
    """
    True only for the specific benign race of a concurrent insert
    losing to Interaction.message_id's unique constraint. Never true
    for any other IntegrityError (a foreign-key violation, a different
    unique constraint) — those must still fall through to the existing
    genuine-failure handling unchanged.
    """

    if not isinstance(exc, IntegrityError):
        return False

    orig = getattr(exc, "orig", None)
    constraint_name = getattr(orig, "constraint_name", None)
    if constraint_name is not None:
        return constraint_name == MESSAGE_ID_UNIQUE_CONSTRAINT_NAME

    return MESSAGE_ID_UNIQUE_CONSTRAINT_NAME in str(orig if orig is not None else exc)

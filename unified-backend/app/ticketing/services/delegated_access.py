# delegated_access.py
"""
Single point of composition for "does this user have a legitimate
delegated relationship to this interaction's THREAD" — the one
question all three delegation/access sources (Manual Forward, Rule
Forward, Folder Share) answer together, for both the view path
(OpenEmailService) and the action path (InteractionService/
InboxTicketService). Not a new access system: this only calls the two
mechanisms that already exist and answer this question on their own —
`forward_access.is_forwarded_to_user` (shared by manual- and
rule-forward, since both write the identical FORWARD-shaped
Interaction row) and `MailFolderService.resolve_folder_access`
(folder sharing) — and returns both results so a caller can OR them
together however its own action's rules require.

Thread-scoped, not row-scoped: `is_forwarded_to_user` already resolves
to the thread root internally regardless of which row is passed. The
folder-share half here does the same — a folder-shared root's replies/
forwards/descendants all resolve delegated access through the root's
own folder_id, since only a thread's root is ever filed into a custom
folder in practice (Rule-driven filing only ever acts on the inbound
root email, and the one manual "Move to Folder" UI surface is a
list-view-root affordance). Without this, a reply/forward child under
a genuinely shared thread would report `folder_shared_bypass=False`
merely because that child's own `folder_id` is unset.
"""

from shared_models.models import User

from app.ticketing.models.interaction import Interaction
from app.ticketing.repositories.distribution_list_repository import (
    DistributionListRepository,
)
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.services.forward_access import is_forwarded_to_user
from app.ticketing.services.mail_folder_service import MailFolderService


async def resolve_delegated_thread_access(
    interaction: Interaction,
    current_user: User,
    *,
    interaction_repository: InteractionRepository,
    mail_folder_repository: MailFolderRepository | None = None,
    rule_repository: RuleRepository | None = None,
    distribution_list_repository: DistributionListRepository | None = None,
) -> tuple[bool, bool]:
    """
    Returns (is_forward_recipient, folder_shared_bypass) for
    `interaction`'s thread — both computed thread-scoped regardless of
    whether `interaction` itself is the root or a descendant.

    Every one of the three optional repositories is genuinely optional
    (mirrors the pattern OpenEmailService's own constructor already
    established): a caller that doesn't wire them up simply never gets
    the folder-share bypass, degrading safely to "no access" rather
    than erroring — the forward-recipient half needs no repository
    beyond `interaction_repository`, which is required.
    """

    is_forward_recipient = await is_forwarded_to_user(
        interaction_repository, interaction, current_user
    )

    folder_shared_bypass = False
    if (
        mail_folder_repository is not None
        and rule_repository is not None
        and distribution_list_repository is not None
    ):
        # A ticketed thread has no folder_id-based sharing concept —
        # folders only ever hold pre-ticket mail (see MailFolderService's
        # own docstring) — so only resolve this for a pending thread.
        if interaction.ticket_id is None:
            root = await interaction_repository.find_thread_root(
                interaction.interaction_id
            )
            target = root if root is not None else interaction
            if target.folder_id is not None:
                folder = await mail_folder_repository.get_by_id(target.folder_id)
                if folder is not None:
                    access = await MailFolderService(
                        mail_folder_repository
                    ).resolve_folder_access(
                        folder,
                        current_user,
                        rule_repository,
                        distribution_list_repository,
                    )
                    folder_shared_bypass = access.via_sharing

    return is_forward_recipient, folder_shared_bypass

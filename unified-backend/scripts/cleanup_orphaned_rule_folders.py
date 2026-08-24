"""
One-time administrative cleanup: delete every existing MailFolder that
is (a) rule-created (is_rule_created=True, see the d4f7b9c1e3a8
backfill migration) and (b) no longer referenced by any current rule's
create_folder/move_to_folder action — the exact class of folder
RuleService.delete's own cleanup step is supposed to remove the moment
its owning rule is deleted, but couldn't for any folder that predates
today's is_rule_created fix (it always evaluated as "not rule-created"
before the backfill, so it was unconditionally preserved instead).

Never deletes an interaction/ticket/attachment/audit row — every
affected interaction's folder_id is cleared first (same
InteractionRepository.clear_folder_for_folder_id RuleService.delete
already uses), so the message just returns to the normal Inbox.

Safe to run more than once: a second run finds zero orphaned rule-
created folders left and does nothing. Run with:
    .venv\\Scripts\\python.exe scripts\\cleanup_orphaned_rule_folders.py
"""

import asyncio

from app.database.session import AsyncSessionLocal, engine
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.mail_folder_repository import MailFolderRepository
from app.ticketing.repositories.rule_repository import RuleRepository
from app.ticketing.services.rule_folder_sync import folder_names_from_actions


async def main() -> None:
    async with AsyncSessionLocal() as db:
        rule_repository = RuleRepository(db)
        mail_folder_repository = MailFolderRepository(db)
        interaction_repository = InteractionRepository(db)

        rules = await rule_repository.list_all()
        referenced_names: set[str] = set()
        for rule in rules:
            referenced_names |= folder_names_from_actions(rule.actions)

        folders = await mail_folder_repository.list_all()

        deleted = []
        for folder in folders:
            if folder.name in referenced_names:
                continue
            if not folder.is_rule_created:
                print(f"SKIP (not rule-created): {folder.name!r} ({folder.folder_id})")
                continue

            affected = await interaction_repository.clear_folder_for_folder_id(folder.folder_id)
            await mail_folder_repository.delete(folder)
            deleted.append((folder.name, folder.folder_id, affected))
            print(f"DELETED: {folder.name!r} ({folder.folder_id}) — unfiled {affected} interaction(s)")

        await db.commit()

        print()
        print(f"Done. Deleted {len(deleted)} orphaned rule-created folder(s).")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

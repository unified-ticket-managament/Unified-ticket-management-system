import asyncio
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from shared_models.models import User
from app.database.session import AsyncSessionLocal, engine
from app.ticketing.repositories.interaction_repository import InteractionRepository
from app.ticketing.repositories.client_repository import ClientRepository
from app.rbac.repositories.role_permission_repository import RolePermissionRepository
from app.rbac.repositories.permission_override_repository import PermissionOverrideRepository
from app.rbac.services.permission_resolver import PermissionResolverService
from app.ticketing.services.access_control import ensure_agent_can_view_pending_interaction, ensure_has_permission
from fastapi import HTTPException

async def main():
    async with AsyncSessionLocal() as session:
        repo = InteractionRepository(session)
        root = await repo.find_thread_root("1d7e60d5-170d-4454-984e-4fd268fdf67f")
        print("root ticket_id:", root.ticket_id, "client_id:", root.client_id)

        uresult = await session.execute(
            select(User).options(joinedload(User.role))
            .where(User.user_id == "ed6d65d0-0411-4f24-a81a-8a591c9bce6d")
        )
        user = uresult.unique().scalar_one()
        resolver = PermissionResolverService(
            role_permission_repository=RolePermissionRepository(session),
            permission_override_repository=PermissionOverrideRepository(session),
        )
        perms, overrides, scoped = await resolver.get_effective_permissions(user)
        user.permissions = perms
        print("has communication:reply_external RIGHT NOW:", "communication:reply_external" in perms)

        client_repository = ClientRepository(session)
        try:
            await ensure_agent_can_view_pending_interaction(
                root, user, client_repository, permission_backed="communication:reply_external"
            )
            ensure_has_permission(user, "communication:reply_external")
            print("RESULT: PASSED -- this exact thread's reply/draft-save check succeeds right now.")
        except HTTPException as e:
            print(f"RESULT: RAISED {e.status_code} - {e.detail}")
    await engine.dispose()

asyncio.run(main())

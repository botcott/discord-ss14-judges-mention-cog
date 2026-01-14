import uuid
from typing import Dict, Optional, Any, List

from sqlalchemy import select, and_, func, or_

from database import async_session_maker, engine
from database.models import ServerBan, ServerRoleBan, AdminNotes, ServerUnBan, ServerRoleUnBan

class BansInfo:
    @staticmethod
    async def get_all_active_bans(user_id: str) -> Optional[List[ServerBan]]:
        async with async_session_maker() as session:
            active_bans = await session.execute(
                select(ServerBan)
                .outerjoin(ServerUnBan, ServerBan.server_ban_id == ServerUnBan.ban_id)
                .where(
                    ServerBan.player_user_id == user_id,
                    ServerUnBan.ban_id.is_(None),
                    or_(
                        ServerBan.expiration_time > func.now(),
                        ServerBan.expiration_time.is_(None)
                    )
                )
            )
            return active_bans.scalars().all()

    @staticmethod
    async def get_all_active_role_bans(user_id: str) -> Optional[List[ServerRoleBan]]:
        async with async_session_maker() as session:
            active_role_bans = await session.execute(
                select(ServerRoleBan)
                .outerjoin(ServerRoleUnBan, ServerRoleBan.server_role_ban_id == ServerRoleUnBan.ban_id)
                .where(
                    ServerRoleBan.player_user_id == user_id,
                    ServerRoleUnBan.ban_id.is_(None),
                    or_(
                        ServerRoleBan.expiration_time > func.now(),
                        ServerRoleBan.expiration_time.is_(None)
                    )
                )
            )
            return active_role_bans.scalars().all()

    @staticmethod
    async def get_all_active_notes(user_id: str) -> Optional[List[AdminNotes]]:
        async with async_session_maker() as session:
            active_role_bans = await session.execute(
                select(AdminNotes)
                .where(
                    AdminNotes.player_user_id == user_id,
                    AdminNotes.deleted.is_(False),
                    or_(
                        AdminNotes.expiration_time > func.now(),
                        AdminNotes.expiration_time.is_(None)
                    )
                )
            )
            return active_role_bans.scalars().all()

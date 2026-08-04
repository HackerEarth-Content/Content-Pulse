"""Shared route dependencies: the caller's member row, and role gating."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.orm import Member, User
from core.users import current_user

WRITERS = ("content", "ae", "manager", "admin")
ADMINS = ("admin",)
AE = ("ae", "manager", "admin")


async def get_member(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> Member | None:
    """None for a signed-in user with no linked members row — they can read,
    but every write goes through require_member below."""
    return await db.scalar(select(Member).where(Member.user_id == user.id))


def require_member(*roles: str):
    allowed = roles or WRITERS

    async def dep(member: Member | None = Depends(get_member)) -> Member:
        if member is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {"code": "no_member", "detail": "Your account isn't linked to a team member."},
            )
        if member.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {"code": "wrong_role", "detail": f"Requires one of: {', '.join(allowed)}."},
            )
        return member

    return dep

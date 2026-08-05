"""Shared route dependencies: the caller's member row, and role gating."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
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
    """The caller's member row, or None if their account isn't linked to one.

    Claims an unlinked row matching their email on the way past. Linking used to
    happen only in the OAuth callback, so adding your own member row while
    already signed in did nothing until you signed out and back in.
    """
    if member := await db.scalar(select(Member).where(Member.user_id == user.id)):
        return member

    member = await db.scalar(
        select(Member).where(
            func.lower(Member.email) == (user.email or "").lower(),
            Member.user_id.is_(None),
            Member.is_active.is_(True),
        )
    )
    if member:
        member.user_id = user.id
        await db.commit()
    return member


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

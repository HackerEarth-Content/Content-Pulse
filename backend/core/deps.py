"""Who is asking, and what they're allowed to see.

One rule, in one place. Every route that returns member-attributable data takes
`Viewer` and honours `scope_member_id` — applying scoping per-route is how a
leak eventually ships.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_session
from core.orm import Member, User
from core.users import current_user

ADMINS = ("admin",)
LEADS = ("admin", "manager")  # may read and write on anyone's behalf


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


@dataclass(frozen=True)
class Viewer:
    user: User
    member: Member | None

    @property
    def role(self) -> str | None:
        return self.member.role if self.member else None

    @property
    def is_lead(self) -> bool:
        """Admins and managers see and act across the whole team."""
        return self.role in LEADS

    @property
    def scope_member_id(self) -> int | None:
        """None means unrestricted. Otherwise every row-level query is pinned to
        this member, whatever the request asked for."""
        if self.is_lead:
            return None
        return self.member.id if self.member else -1  # unlinked: matches nothing

    def scope(self, requested: int | None) -> int | None:
        """Resolve a `member_id` query param against what this viewer may read.

        A member asking for someone else's id is silently pinned to their own
        rather than refused — a 403 would confirm that the other id exists.
        """
        return requested if self.is_lead else self.scope_member_id

    def may_write_for(self, member_id: int) -> bool:
        return self.is_lead or (self.member is not None and self.member.id == member_id)

    def writer_id(self, requested: int | None) -> int:
        """The member a new entry belongs to. Leads may name anyone; everyone
        else files as themselves regardless of what the client sent."""
        if self.is_lead:
            if requested is None:
                raise _forbidden("member_required", "Choose which member this is for.")
            return requested
        if self.member is None:
            raise _forbidden("no_member", "Your account isn't linked to a team member.")
        return self.member.id


def _forbidden(code: str, detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, {"code": code, "detail": detail})


async def get_viewer(
    user: User = Depends(current_user), member: Member | None = Depends(get_member)
) -> Viewer:
    return Viewer(user=user, member=member)


def require_role(*roles: str):
    """Route guard for things only some roles may do at all."""
    allowed = roles or LEADS

    async def dep(viewer: Viewer = Depends(get_viewer)) -> Viewer:
        # Super-admins are defined in env, so they work before any member row
        # exists — otherwise the screen used to grant roles is itself locked.
        if (viewer.user.email or "").lower() in settings.superadmins:
            return viewer
        if viewer.member is None:
            raise _forbidden("no_member", "Your account isn't linked to a team member.")
        if viewer.member.role not in allowed:
            raise _forbidden("wrong_role", f"Requires one of: {', '.join(allowed)}.")
        return viewer

    return dep


# Kept for the AE routes, which gate on role rather than on scope.
def require_member(*roles: str):
    return require_role(*roles)

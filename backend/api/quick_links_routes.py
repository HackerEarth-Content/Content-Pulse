from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.deps import Viewer, get_viewer
from core.orm import QuickLink
from core.users import current_user
from schemas.quick_links import QuickLinkIn, QuickLinkOut, QuickLinkPatch

router = APIRouter(
    prefix="/api/quick-links",
    tags=["quick-links"],
    dependencies=[Depends(current_user)],
)


def _member_required(viewer: Viewer) -> int:
    if viewer.member is None:
        raise HTTPException(
            403,
            {
                "code": "no_member",
                "detail": "Your account isn't linked to a team member.",
            },
        )
    return viewer.member.id


@router.get("", response_model=list[QuickLinkOut])
async def list_quick_links(
    member_id: int | None = None,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    # Leads may look up anyone; everyone else only ever sees their own —
    # `viewer.scope` already pins a non-lead's request to themselves.
    target = (
        viewer.scope(member_id) if member_id is not None else _member_required(viewer)
    )
    rows = await db.scalars(
        select(QuickLink)
        .where(QuickLink.member_id == target)
        .order_by(QuickLink.sort_order, QuickLink.id)
    )
    return list(rows)


@router.post("", response_model=QuickLinkOut, status_code=201)
async def create_quick_link(
    body: QuickLinkIn,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    # Always saved as yourself — a lead browsing someone else's links (view
    # only, per the tab's design) never gets a write path here.
    link = QuickLink(member_id=_member_required(viewer), **body.model_dump())
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def _own_link(db: AsyncSession, viewer: Viewer, link_id: int) -> QuickLink:
    link = await db.get(QuickLink, link_id)
    if link is None or link.member_id != _member_required(viewer):
        raise HTTPException(404, {"code": "not_found", "detail": "Link not found."})
    return link


@router.patch("/{link_id}", response_model=QuickLinkOut)
async def patch_quick_link(
    link_id: int,
    body: QuickLinkPatch,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    link = await _own_link(db, viewer, link_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(link, field, value)
    await db.commit()
    await db.refresh(link)
    return link


@router.delete("/{link_id}", status_code=204)
async def delete_quick_link(
    link_id: int,
    db: AsyncSession = Depends(get_session),
    viewer: Viewer = Depends(get_viewer),
):
    link = await _own_link(db, viewer, link_id)
    await db.delete(link)
    await db.commit()

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

import services.holidays as svc
from core.database import get_session
from core.deps import ADMINS, require_role
from core.users import current_user
from schemas.holidays import HolidayIn, HolidayOut

router = APIRouter(
    prefix="/api/holidays", tags=["holidays"], dependencies=[Depends(current_user)]
)
admin_only = Depends(require_role(*ADMINS))


@router.get("", response_model=list[HolidayOut])
async def list_holidays(db: AsyncSession = Depends(get_session)):
    return await svc.list_holidays(db)


@router.post("", response_model=list[HolidayOut], dependencies=[admin_only])
async def add_holiday(body: HolidayIn, db: AsyncSession = Depends(get_session)):
    await svc.add_holiday(db, body.date, body.name.strip())
    return await svc.list_holidays(db)


@router.delete("/{on}", response_model=list[HolidayOut], dependencies=[admin_only])
async def remove_holiday(on: date, db: AsyncSession = Depends(get_session)):
    await svc.remove_holiday(db, on)
    return await svc.list_holidays(db)

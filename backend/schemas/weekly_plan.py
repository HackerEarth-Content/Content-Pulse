from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from core.orm import WEEKLY_PLAN_STATUSES


class WeeklyPlanItemIn(BaseModel):
    week_start: date
    action: str = Field(min_length=1)


class WeeklyPlanItemPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(" + "|".join(WEEKLY_PLAN_STATUSES) + ")$")
    achievement: str | None = None


class WeeklyPlanItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    member_id: int
    member: str
    week_start: date
    action: str
    achievement: str | None
    status: str
    updated_at: datetime

    @classmethod
    def of(cls, item) -> WeeklyPlanItemOut:
        return cls(
            id=item.id, member_id=item.member_id, member=item.member.display_name,
            week_start=item.week_start, action=item.action, achievement=item.achievement,
            status=item.status, updated_at=item.updated_at,
        )


class WeeklyPlanCompletionOut(BaseModel):
    active: int
    filed: int
    updated: int

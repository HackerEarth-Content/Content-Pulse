from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.orm import SKILL_CATEGORIES

CATEGORY_PATTERN = "^(" + "|".join(SKILL_CATEGORIES) + ")$"


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SkillOut(ORMModel):
    id: int
    name: str
    category: str
    sub_domain: str | None


class SkillIn(BaseModel):
    name: str = Field(min_length=1)
    category: str = Field(pattern=CATEGORY_PATTERN)
    sub_domain: str | None = None
    sort_order: int = 0


class SkillPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, pattern=CATEGORY_PATTERN)
    sub_domain: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class RatingIn(BaseModel):
    skill_id: int
    level: int = Field(ge=1, le=5)


class RatingsBulkIn(BaseModel):
    ratings: list[RatingIn]


class RatingOut(BaseModel):
    skill_id: int
    level: int
    rated_at: datetime


class WindowOut(BaseModel):
    open: bool
    open_weekdays: list[int]
    excluded_member_ids: list[int]


class WindowPatch(BaseModel):
    open_weekdays: list[int] | None = None
    excluded_member_ids: list[int] | None = None


class MemberRatings(BaseModel):
    """One member's ratings, keyed by skill id — the shape the graph views
    index into directly rather than scanning a list per lookup."""

    member_id: int
    display_name: str
    role: str
    ratings: dict[int, int]


class SkillGraphOut(BaseModel):
    skills: list[SkillOut]
    members: list[MemberRatings]

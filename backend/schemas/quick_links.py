from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class QuickLinkIn(BaseModel):
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)


class QuickLinkPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    url: str | None = Field(default=None, min_length=1)


class QuickLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    member_id: int
    name: str
    url: str
    sort_order: int
    updated_at: datetime

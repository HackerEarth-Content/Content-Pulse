from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class LeaveDatesIn(BaseModel):
    dates: list[date] = Field(min_length=1)


class LeaveOut(BaseModel):
    dates: list[str]

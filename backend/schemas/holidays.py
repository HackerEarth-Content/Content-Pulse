from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class HolidayIn(BaseModel):
    date: date
    name: str = Field(min_length=1)


class HolidayOut(BaseModel):
    date: str
    name: str

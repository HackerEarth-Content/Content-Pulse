from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TaxonomyTagIn(BaseModel):
    category: str = Field(min_length=1)
    tag: str = Field(min_length=1)


class TaxonomyTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    tag: str


class TaxonomyGroup(BaseModel):
    category: str
    tags: list[TaxonomyTagOut]

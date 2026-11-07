"""Shapes of everything Gemini returns (sent as structured-output schemas and validated with Pydantic).
Boxes are [ymin, xmin, ymax, xmax] in 0..1000 image coordinates."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Box = list[float]


def box_field(description: str = "[ymin, xmin, ymax, xmax] in 0-1000 image coordinates"):
    return Field(description=description, min_length=4, max_length=4)


class FloorZone(BaseModel):
    id: str = Field(description='"z1", "z2", ...')
    box_2d: Box = box_field("the visible empty floor area, [ymin, xmin, ymax, xmax] 0-1000")
    description: str


class Analysis(BaseModel):
    room_type: str
    style: str
    lighting: str
    free_floor_zones: list[FloorZone]


class Pick(BaseModel):
    id: str = Field(description='"s1", "s2", ... ; a referenced slot comes first')
    product_ref: str = Field(description='the product reference from the list, e.g. "p3"')
    role: str
    zone_id: str
    layout: str = Field(description="against_wall | center | in_front_of:sX | beside:sX | under:sX | on_top_of:sX")


class Tweak(BaseModel):
    type: Literal["lighting", "wall", "plant", "textile", "declutter", "other"]
    instruction: str


class Plan(BaseModel):
    vibe: str
    picks: list[Pick]
    tweaks: list[Tweak]


class Design(BaseModel):
    analysis: Analysis
    plan: Plan


class FoundItem(BaseModel):
    n: int
    found: bool
    box_2d: Box | None = Field(default=None, description="tight box around the whole piece, 0-1000; null if not found")


class Detection(BaseModel):
    items: list[FoundItem]

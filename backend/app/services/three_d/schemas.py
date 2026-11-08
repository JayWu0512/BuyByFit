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
    box_2d: Box = box_field("the visible EMPTY floor area (no furniture standing on it), [ymin, xmin, ymax, xmax] 0-1000")
    description: str


class ExistingItem(BaseModel):
    label: str = Field(description='a piece of furniture already in the room, e.g. "bed", "dining chair", "desk"')
    box_2d: Box = box_field("tight box around the whole piece, [ymin, xmin, ymax, xmax] 0-1000")
    keep: bool = Field(default=True, description="false only if a pick replaces this piece (its label goes in "
                                                 "that pick's replaces)")


class Analysis(BaseModel):
    room_type: str
    style: str
    lighting: str
    existing: list[ExistingItem] = Field(default_factory=list,
                                         description="every piece of furniture already in the photo")
    free_floor_zones: list[FloorZone]


class Pick(BaseModel):
    id: str = Field(description='"s1", "s2", ... ; a referenced slot comes first')
    product_ref: str = Field(description='the product reference from the list, e.g. "p3"')
    role: str
    zone_id: str
    layout: str = Field(description="against_wall | center | in_front_of:sX | beside:sX | under:sX | on_top_of:sX")
    replaces: str = Field(default="", description='label of the existing piece this pick replaces (e.g. "dining '
                                                  'table"), or "" if it is an addition')


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


class RoomContext(BaseModel):
    room_type: str
    style: str = Field(description="current colors/materials/style, briefly")
    needs: list[str] = Field(
        description="up to 4 furniture/decor categories this room is missing or could use, most important "
        "first (e.g. an empty bedroom needs a bed, nightstand, dresser -- not just lamps or decor)",
        max_length=4,
    )


class FoundItem(BaseModel):
    n: int
    found: bool
    box_2d: Box | None = Field(default=None, description="tight box around the whole piece, 0-1000; null if not found")


class Detection(BaseModel):
    items: list[FoundItem]


class ExtraItem(BaseModel):
    description: str = Field(
        description='short description of the piece, e.g. "a woven jute rug under the bed" or "a floor lamp '
        'by the window"'
    )


class Extras(BaseModel):
    extras: list[ExtraItem] = Field(
        description="furniture, rugs, or large decor visible in the image that is not one of the numbered "
        "products and isn't explained by an approved styling touch -- i.e. something the model drew in on "
        "its own that isn't part of the plan. Empty if there's nothing extra.",
        max_length=6,
    )

from typing import Any

from pydantic import BaseModel, Field


class ExtractedEntity(BaseModel):
    type: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    # 维度 -> 取值，如 {"五行": "水"}
    classifications: dict[str, str] = Field(default_factory=dict)
    # 类型专属字段，值可能是字符串/列表/数字，故用 Any
    attrs: dict[str, Any] = Field(default_factory=dict)
    evidence: str = ""


class ExtractedRelation(BaseModel):
    from_name: str
    to_name: str
    type: str
    attrs: dict[str, Any] = Field(default_factory=dict)
    evidence: str = ""


class ChapterExtraction(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)

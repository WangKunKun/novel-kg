from typing import Any

from pydantic import BaseModel, Field, field_validator


def _coerce_attrs(v: Any) -> Any:
    # LLM 偶尔把 attrs 直接给成字符串（如 "师徒"），包成 {"note": ...} 无损保留
    if isinstance(v, str):
        return {"note": v}
    return v


class ExtractedEntity(BaseModel):
    type: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    # 维度 -> 取值，如 {"五行": "水"}
    classifications: dict[str, str] = Field(default_factory=dict)
    # 类型专属字段，值可能是字符串/列表/数字，故用 Any
    attrs: dict[str, Any] = Field(default_factory=dict)
    evidence: str = ""

    _attrs_coerce = field_validator("attrs", mode="before")(_coerce_attrs)


class ExtractedRelation(BaseModel):
    from_name: str
    to_name: str
    type: str
    attrs: dict[str, Any] = Field(default_factory=dict)
    evidence: str = ""

    _attrs_coerce = field_validator("attrs", mode="before")(_coerce_attrs)


class ChapterExtraction(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)

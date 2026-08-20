from pydantic import BaseModel, Field


class EntityTypeDef(BaseModel):
    fields: list[str] = Field(default_factory=list)
    classify_by: list[str] = Field(default_factory=list)
    # 类型定义/判别标准，渲染进抽取 prompt，帮 LLM 区分易混类型
    description: str = ""


class RelationTypeDef(BaseModel):
    name: str
    from_type: str | None = None
    to_type: str | None = None
    description: str = ""


class SchemaConfig(BaseModel):
    entity_types: dict[str, EntityTypeDef]
    relation_types: list[RelationTypeDef]
    classification_dimensions: dict[str, list[str]] = Field(default_factory=dict)
    # 维度 -> {取值: 父取值 or None}，表示分类树
    taxonomy_parents: dict[str, dict[str, str | None]] = Field(default_factory=dict)

    def relation_type(self, name: str) -> RelationTypeDef | None:
        for rt in self.relation_types:
            if rt.name == name:
                return rt
        return None


def load_config(path: str) -> SchemaConfig:
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return SchemaConfig.model_validate(data)

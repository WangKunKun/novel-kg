from novel_kg.config import SchemaConfig
from novel_kg.ingest import Chapter
from novel_kg.llm_client import LLMClient
from novel_kg.models import ChapterExtraction


def build_system_prompt(schema: SchemaConfig) -> str:
    lines = ["你是一个小说信息抽取助手。从给定章节中抽取实体和关系，严格只返回 JSON。"]

    lines.append("\n【实体类型】及字段：")
    for name, defn in schema.entity_types.items():
        extra = f"；分类维度{defn.classify_by}" if defn.classify_by else ""
        lines.append(f"- {name}：字段{defn.fields}{extra}")

    if schema.classification_dimensions:
        lines.append("\n【分类维度可选值】（取值必须来自下列，未知则留空，禁止编造）：")
        for dim, vals in schema.classification_dimensions.items():
            lines.append(f"- {dim}：{', '.join(vals)}")

    lines.append("\n【关系类型】（type 取下列之一，from_name/to_name 用本章出现的实体名）：")
    for rt in schema.relation_types:
        lines.append(f"- {rt.name}：{rt.from_type} -> {rt.to_type}")

    lines.append(
        "\n【输出 JSON 格式】\n"
        '{"entities":[{"type","name","aliases":[],"classifications":{},"attrs":{},"evidence":"本章原文片段"}],'
        '"relations":[{"from_name","to_name","type","attrs":{},"evidence":"本章原文片段"}]}\n'
        "\n硬性要求：1) 每条实体和关系都必须有 evidence（本章原文片段）。"
        "2) 拿不准的字段留空，不要编造。3) 只输出 JSON，不要解释。"
    )
    return "\n".join(lines)


def extract_chapter(
    client: LLMClient, schema: SchemaConfig, chapter: Chapter
) -> ChapterExtraction:
    system = build_system_prompt(schema)
    user = f"第{chapter.index}章 {chapter.title}\n\n{chapter.text}"
    raw = client.complete_json(system, user)
    return ChapterExtraction.model_validate(raw)

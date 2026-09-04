from novel_kg.config import SchemaConfig
from novel_kg.ingest import Chapter
from novel_kg.llm_client import LLMClient
from novel_kg.models import ChapterExtraction


def build_system_prompt(schema: SchemaConfig) -> str:
    lines = ["你是一个小说信息抽取助手。从给定章节中抽取实体和关系，严格只返回 JSON。"]

    lines.append("\n【实体类型】及字段（判别标准必须遵守，拿不准归入最接近的一类）：")
    for name, defn in schema.entity_types.items():
        extra = f"；分类维度{defn.classify_by}" if defn.classify_by else ""
        desc = f"。{defn.description}" if defn.description else ""
        lines.append(f"- {name}：字段{defn.fields}{extra}{desc}")

    if schema.classification_dimensions:
        lines.append("\n【分类维度可选值】（取值必须来自下列，未知则留空，禁止编造）：")
        for dim, vals in schema.classification_dimensions.items():
            lines.append(f"- {dim}：{', '.join(vals)}")

    lines.append("\n【关系类型】（type 取下列之一，from_name/to_name 用本章出现的实体名，端点实体类型必须匹配）：")
    for rt in schema.relation_types:
        desc = f"（{rt.description}）" if rt.description else ""
        lines.append(f"- {rt.name}：{rt.from_type} -> {rt.to_type}{desc}")

    lines.append(
        "\n【输出 JSON 格式】\n"
        '{"entities":[{"type","name","aliases":[],"classifications":{},"attrs":{},"evidence":"本章原文片段"}],'
        '"relations":[{"from_name","to_name","type","attrs":{},"evidence":"本章原文片段"}]}\n'
        "\n硬性要求：1) 每条实体和关系都必须有 evidence（本章原文片段）。"
        "2) 拿不准的字段留空，不要编造。3) 只输出 JSON，不要解释。"
        "4) 人物的别名放进 entities[].aliases 数组，不要放进 attrs；attrs 的值都用字符串。"
    )
    return "\n".join(lines)


def extract_chapter(
    client: LLMClient, schema: SchemaConfig, chapter: Chapter
) -> ChapterExtraction:
    system = build_system_prompt(schema)
    user = f"第{chapter.index}章 {chapter.title}\n\n{chapter.text}"
    try:
        raw = client.complete_json(system, user)
    except RuntimeError as e:
        # 智谱内容安全过滤（1301）：同输入必然同结果，重试无意义。
        # 返回空抽取让管道继续，该章事后可用 SQL 找回：
        # SELECT chapter FROM extractions WHERE raw_json LIKE '%"entities": []%';
        if "1301" in str(e) or "contentFilter" in str(e):
            return ChapterExtraction(entities=[], relations=[])
        raise
    return ChapterExtraction.model_validate(raw)

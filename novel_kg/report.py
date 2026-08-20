import json

from novel_kg.store import DB, evolution_text, relation_label


def generate_report(db: DB) -> str:
    lines: list[str] = ["# 小说分析报告", ""]

    # 统计
    lines.append("## 实体统计")
    counts = db.entity_counts()
    if counts:
        for r in counts:
            lines.append(f"- {r['type']}：{r['n']}")
    else:
        lines.append("- （暂无数据）")
    lines.append("")

    # 各类型实体清单
    for r in counts:
        t = r["type"]
        lines.append(f"## {t}")
        for e in db.list_entities(t):
            attrs = json.loads(e["attrs_json"] or "{}")
            cls = db.list_classifications(e["id"])
            cls_str = "；".join(f"{c['dimension']}:{c['value']}" for c in cls)
            attr_str = "；".join(f"{k}:{v}" for k, v in attrs.items())
            badge = "（待确认）" if e["status"] == "pending_review" else ""
            parts = [p for p in (cls_str, attr_str) if p]
            lines.append(f"- **{e['name']}**{badge}" + (f"：{'；'.join(parts)}" if parts else ""))
        lines.append("")

    # 势力关系演变（事件流时间线）
    lines.append("## 势力关系演变")
    name_by_id0 = {e["id"]: e["name"] for e in db.list_entities()}
    faction_events = db.list_relation_events("势力关系")
    if faction_events:
        pairs: dict[tuple[str, str], list[dict]] = {}
        for ev in faction_events:
            pairs.setdefault((ev["from_id"], ev["to_id"]), []).append(ev)
        for (fid, tid), evs in pairs.items():
            a = name_by_id0.get(fid, "?")
            b = name_by_id0.get(tid, "?")
            lines.append(f"### {a} → {b}")
            lines.append(f"- 演变：{evolution_text(evs)}")
            for ev in evs:
                lines.append(f"  - 第{ev['chapter']}章：{ev['evidence'] or '（无证据）'}")
    else:
        lines.append("- （暂无势力关系事件）")
    lines.append("")

    # 关系
    rels = db.list_relations()
    lines.append(f"## 关系（共 {len(rels)} 条）")
    name_by_id = {e["id"]: e["name"] for e in db.list_entities()}
    for rel in rels[:200]:  # 报告里截断，全量看可视化
        a = name_by_id.get(rel["from_id"], "?")
        b = name_by_id.get(rel["to_id"], "?")
        lines.append(f"- {a} --{relation_label(rel)}--> {b}")
    return "\n".join(lines)

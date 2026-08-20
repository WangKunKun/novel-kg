import os
import sys

# 允许直接 `streamlit run novel_kg/viz_app.py` 从项目根启动：streamlit
# 执行脚本时只把脚本所在目录加入 sys.path，不含项目根，会导致
# `from novel_kg.store import DB` 找不到包。这里手动把项目根（本文件
# 所在目录的上一级）加入模块搜索路径。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
from pyvis.network import Network

from novel_kg.store import DB, evolution_text, relation_label


def load_graph(db: DB, entity_type: str | None = None,
               rel_type: str | None = None,
               as_of: int | None = None) -> tuple[list[dict], list[dict]]:
    """从 DB 读实体与关系，可按类型过滤。as_of=第X章时用事件流的当时状态。"""
    entities = db.list_entities(entity_type)
    ent_ids = {e["id"] for e in entities}
    rels = db.relations_as_of(as_of) if as_of else db.list_relations()
    rels = [r for r in rels
            if r["from_id"] in ent_ids and r["to_id"] in ent_ids
            and (rel_type is None or r["type"] == rel_type)]
    return entities, rels


def render_network(entities: list[dict], rels: list[dict],
                   evolution: dict[str, str] | None = None) -> Network:
    type_colors = {"人物": "#e6194b", "势力": "#3cb44b", "仙基": "#4363d8",
                   "道具": "#f58231", "功法": "#911eb4", "术法": "#46f0f0"}
    # cdn_resources="in_line"：把 vis-network 的 JS 内联进 HTML，避免在
    # streamlit 的受限 iframe 里加载远程 CDN 失败导致图谱区域空白
    net = Network(height="600px", width="100%", bgcolor="#ffffff",
                  cdn_resources="in_line")
    name_by_id = {}
    for e in entities:
        name_by_id[e["id"]] = e["name"]
        net.add_node(e["id"], label=e["name"],
                     color=type_colors.get(e["type"], "#999999"),
                     title=f"{e['type']}｜{e['name']}")
    for r in rels:
        key = f"{r['from_id']}->{r['to_id']}"
        evo = (evolution or {}).get(key)
        title = r.get("evidence", "")
        if evo:
            title = f"演变：{evo}\n证据：{title}"
        net.add_edge(r["from_id"], r["to_id"], label=relation_label(r), title=title)
    return net


def main() -> None:
    st.set_page_config(page_title="小说知识图谱", layout="wide")
    st.title("📚 小说知识图谱")
    db_path = st.sidebar.text_input("SQLite 路径", "data/novel.db")
    db = DB(db_path)

    types = [r["type"] for r in db.entity_counts()]
    sel_type = st.sidebar.selectbox("实体类型筛选", ["（全部）"] + types)
    rel_types = sorted({r["type"] for r in db.list_relations()})
    sel_rel = st.sidebar.selectbox("关系类型筛选", ["（全部）"] + rel_types)

    et = None if sel_type == "（全部）" else sel_type
    rt = None if sel_rel == "（全部）" else sel_rel

    max_ch = db.max_relation_chapter()
    as_of = None
    if max_ch:
        pick = st.sidebar.slider("截至章节（拖动回看当时关系）", 1, max_ch, max_ch)
        as_of = pick if pick < max_ch else None  # 拉满即最新

    entities, rels = load_graph(db, et, rt, as_of=as_of)
    st.write(f"实体 {len(entities)} 条，关系 {len(rels)} 条"
             + (f"（截至第 {as_of} 章）" if as_of else ""))

    if entities:
        evolution = {}
        for r in rels:
            hist = db.relation_history(r["from_id"], r["to_id"])
            if as_of:
                hist = [h for h in hist if h["chapter"] <= as_of]
            if len(hist) > 1:
                evolution[f"{r['from_id']}->{r['to_id']}"] = evolution_text(hist)
        net = render_network(entities, rels, evolution)
        net.save_graph("/tmp/novel_kg_graph.html")
        st.components.v1.html(open("/tmp/novel_kg_graph.html", encoding="utf-8").read(),
                              height=620, scrolling=True)

    # 关系演变面板
    st.subheader("📖 关系演变时间线")
    ent_names = sorted(e["name"] for e in db.list_entities())
    if not ent_names:
        st.write("（暂无实体）")
    c1, c2 = st.columns(2)
    a = c1.selectbox("实体甲", ent_names)
    b = c2.selectbox("实体乙", ent_names)
    if a and b and a != b:
        ea = db.find_entity_id_any(a)
        eb = db.find_entity_id_any(b)
        rows = []
        if ea and eb:
            rows = sorted(db.relation_history(ea, eb) + db.relation_history(eb, ea),
                          key=lambda h: h["chapter"])
        if rows:
            st.dataframe([{"章": h["chapter"], "类型": h["type"],
                           "attrs": h["attrs_json"], "证据": h["evidence"]}
                          for h in rows])
        else:
            st.write("（这对实体没有已记录的关系事件）")


if __name__ == "__main__":
    main()

import streamlit as st
from pyvis.network import Network

from novel_kg.store import DB


def load_graph(db: DB, entity_type: str | None = None,
               rel_type: str | None = None) -> tuple[list[dict], list[dict]]:
    """从 DB 读实体与关系，可按类型过滤。供测试与 UI 共用。"""
    entities = db.list_entities(entity_type)
    ent_ids = {e["id"] for e in entities}
    rels = [r for r in db.list_relations()
            if r["from_id"] in ent_ids and r["to_id"] in ent_ids
            and (rel_type is None or r["type"] == rel_type)]
    return entities, rels


def render_network(entities: list[dict], rels: list[dict]) -> Network:
    type_colors = {"人物": "#e6194b", "势力": "#3cb44b", "仙基": "#4363d8",
                   "道具": "#f58231"}
    net = Network(height="600px", width="100%", bgcolor="#ffffff")
    name_by_id = {}
    for e in entities:
        name_by_id[e["id"]] = e["name"]
        net.add_node(e["id"], label=e["name"],
                     color=type_colors.get(e["type"], "#999999"),
                     title=f"{e['type']}｜{e['name']}")
    for r in rels:
        net.add_edge(r["from_id"], r["to_id"], label=r["type"], title=r.get("evidence", ""))
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
    entities, rels = load_graph(db, et, rt)

    st.write(f"实体 {len(entities)} 条，关系 {len(rels)} 条")
    if entities:
        net = render_network(entities, rels)
        net.save_graph("/tmp/novel_kg_graph.html")
        st.components.v1.html(open("/tmp/novel_kg_graph.html", encoding="utf-8").read(),
                              height=620, scrolling=True)


if __name__ == "__main__":
    main()

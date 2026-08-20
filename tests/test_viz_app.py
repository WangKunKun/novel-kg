from novel_kg.viz_app import render_network


def test_render_network_uses_relation_label_for_edges():
    entities = [
        {"id": "人物_1", "type": "人物", "name": "李项平"},
        {"id": "人物_2", "type": "人物", "name": "李木田"},
    ]
    rels = [{"from_id": "人物_1", "to_id": "人物_2", "type": "关系",
             "attrs_json": '{"关系": "父子"}', "evidence": "阿爹"}]
    net = render_network(entities, rels)
    labels = [e.get("label") for e in net.edges]
    assert "父子" in labels         # 边标签显示具体关系
    assert "关系" not in labels     # 不再只写"关系"


def test_load_graph_as_of_uses_event_state(tmp_path):
    from novel_kg.store import DB
    from novel_kg.viz_app import load_graph

    db = DB(str(tmp_path / "g.db"))
    for e in [{"id": "S1", "type": "势力", "name": "李家"},
              {"id": "S2", "type": "势力", "name": "镜铁山"}]:
        db.upsert_entity(e["id"], e["type"], e["name"], e["id"], "{}", 1, 0.9, "confirmed")
    db.record_relation_event("rel_a", "S1", "S2", "势力关系",
                             '{"性质": "附庸"}', 10, "称臣")
    db.record_relation_event("rel_a", "S1", "S2", "势力关系",
                             '{"性质": "敌对"}', 40, "反目")
    # relations 表 = 最新状态（resolve 三态负责同步，这里手动模拟）
    db.upsert_relation("rel_a", "S1", "S2", "势力关系",
                       '{"性质": "敌对"}', 40, "反目")

    _, rels_30 = load_graph(db, as_of=30)
    assert rels_30[0]["attrs_json"] == '{"性质": "附庸"}'
    _, rels_now = load_graph(db)  # 不传 as_of -> 最新（relations 表）
    assert rels_now[0]["attrs_json"] == '{"性质": "敌对"}'


def test_evolution_text_formats_chapters():
    from novel_kg.store import evolution_text

    hist = [
        {"chapter": 10, "attrs_json": '{"性质": "附庸"}'},
        {"chapter": 40, "attrs_json": '{"性质": "敌对"}'},
    ]
    assert evolution_text(hist) == "10章:附庸 → 40章:敌对"


def test_render_network_evolution_hover_title():
    from novel_kg.viz_app import render_network

    entities = [
        {"id": "S1", "type": "势力", "name": "李家"},
        {"id": "S2", "type": "势力", "name": "镜铁山"},
    ]
    rels = [{"from_id": "S1", "to_id": "S2", "type": "势力关系",
             "attrs_json": '{"性质": "敌对"}', "evidence": "反目"}]
    evo = {"S1->S2": "10章:附庸 → 40章:敌对"}
    net = render_network(entities, rels, evo)
    title = net.edges[0]["title"]
    assert title.startswith("演变：10章:附庸 → 40章:敌对")
    assert "证据：反目" in title
    # 无演变时退回纯证据
    net2 = render_network(entities, rels)
    assert net2.edges[0]["title"] == "反目"

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

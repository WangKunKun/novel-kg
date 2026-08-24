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


def test_person_rank_stage_order():
    from novel_kg.viz_app import person_rank

    # 修仙六境从低到高：胎息(1-6) < 练气(10-18) < 筑基(20-22) < 紫府(24) < 金丹(26) < 元婴(28)
    assert person_rank("") == 0                      # 未知/凡人
    # 胎息六轮即六层（原文：胎息一层玄景轮/二层承明轮/四层青元轮/五层玉京轮/六层灵初轮）
    assert person_rank("胎息一层") == 1
    assert person_rank("胎息二层承明轮") == 2
    assert person_rank("胎息四层") == 4
    assert person_rank("胎息五层（玉京轮）") == 5
    assert person_rank("胎息巅峰") == 6
    assert person_rank("玄景轮") == 1
    assert person_rank("玉京轮修士（已在升阳府凝聚灵轮）") == 5
    assert person_rank("灵初轮") == 6
    # 练气按层 +10；"五六层"含"六层"子串取 6
    assert person_rank("练气三层") == 13
    assert person_rank("练气七层") == 17
    assert person_rank("练气中期（约五六层）") == 16  # 括号近似层数也取值
    assert person_rank("练气巅峰") == 18
    assert person_rank("筑基") == 20
    assert person_rank("筑基中期") == 21
    assert person_rank("筑基巅峰") == 22
    assert person_rank("紫府（欲突破金丹）") == 24   # 紫府分支在金丹前，"欲突破金丹"不误升段
    assert person_rank("金丹") == 26
    assert person_rank("远超筑基") == 24


def test_faction_rank_keyword_order():
    from novel_kg.viz_app import faction_rank

    assert faction_rank("仙府") == 9
    assert faction_rank("门派（七门之一）") == 8
    assert faction_rank("凡人国度") == 7
    assert faction_rank("郡中修仙家族") == 5          # 长词优先于"家族"
    assert faction_rank("家族") == 4
    assert faction_rank("黎泾村第一大姓") == 3
    assert faction_rank("") == 0
    assert faction_rank("某个未知组织") == 1


def test_faction_rank_power_over_level():
    from novel_kg.viz_app import faction_rank

    # 顶尖战力优先于组织层级：筑基家族（李家）大于凡人大国（国7→14+…按层级14+7*2? 量纲见 node_size）
    assert faction_rank("村中家族", "筑基") == 9 > faction_rank("凡人国度", "")  # 7
    assert faction_rank("仙府", "金丹") == 12 > faction_rank("仙府", "")        # 9
    assert faction_rank("仙府", "紫府") == 10
    assert faction_rank("仙府", "胎息") == 5 < faction_rank("仙府", "")        # 弱战力反而压低
    assert faction_rank("宗门", "练气") == 7


def test_render_network_node_size_by_rank():
    from novel_kg.viz_app import render_network

    entities = [
        {"id": "P1", "type": "人物", "name": "筑基修士",
         "attrs_json": '{"境界": "筑基"}'},
        {"id": "P2", "type": "人物", "name": "凡人",
         "attrs_json": '{"境界": ""}' },
        {"id": "F1", "type": "势力", "name": "某仙府",
         "attrs_json": '{"层级": "仙府"}'},
    ]
    net = render_network(entities, [])
    sizes = {n["id"]: n["size"] for n in net.nodes}
    assert sizes["P1"] > sizes["P2"]     # 筑基 > 未知
    assert sizes["F1"] == 10 + 9 * 2     # 仙府层级 9
    titles = {n["id"]: n["title"] for n in net.nodes}
    assert "境界：筑基" in titles["P1"]
    assert "境界" not in titles["P2"]    # 空境界不显示行


def test_render_network_item_size_by_grade():
    from novel_kg.viz_app import render_network

    entities = [
        {"id": "I1", "type": "道具", "name": "仙丹", "attrs_json": "{}"},
        {"id": "I2", "type": "道具", "name": "凡铁", "attrs_json": "{}"},
        {"id": "I3", "type": "道具", "name": "无名物", "attrs_json": "{}"},
    ]
    net = render_network(entities, [], grades={"I1": "仙品", "I2": "凡品"})
    sizes = {n["id"]: n["size"] for n in net.nodes}
    assert sizes["I1"] == 19 and sizes["I2"] == 12 and sizes["I3"] == 10

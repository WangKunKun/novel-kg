from novel_kg.config import load_config
from novel_kg.models import ChapterExtraction, ExtractedEntity, ExtractedRelation
from novel_kg.resolve import resolve_extraction
from novel_kg.store import DB


def _ext():
    return ChapterExtraction(
        entities=[
            ExtractedEntity(type="人物", name="林动", aliases=["动哥"],
                            attrs={"境界": "元力"}, evidence="林动凝气"),
            ExtractedEntity(type="势力", name="青阳镇", evidence="林动家住青阳镇"),
        ],
        relations=[
            ExtractedRelation(from_name="林动", to_name="青阳镇", type="所属",
                               evidence="林动家住青阳镇"),
        ],
    )


def test_resolve_creates_entities_merges_aliases_and_links_relations(tmp_path):
    schema = load_config("config/novels/xuanjian.yaml")
    db = DB(str(tmp_path / "t.db"))

    resolve_extraction(db, schema, 1, _ext())

    persons = db.list_entities("人物")
    assert len(persons) == 1
    assert persons[0]["status"] == "confirmed"
    # 别名归并：用别名也能找到同一实体
    assert db.find_entity_id("人物", "动哥") == persons[0]["id"]
    # 关系端点正确解析到实体 id
    rels = db.list_relations()
    assert len(rels) == 1
    assert rels[0]["from_id"] == persons[0]["id"]

    # 幂等：重跑同一章抽取，关系不重复（确定性 id）
    resolve_extraction(db, schema, 1, _ext())
    assert len(db.list_relations()) == 1


def test_low_confidence_when_no_evidence(tmp_path):
    schema = load_config("config/novels/xuanjian.yaml")
    db = DB(str(tmp_path / "t2.db"))
    ext = ChapterExtraction(
        entities=[ExtractedEntity(type="人物", name="无名氏")],  # 无 evidence
        relations=[],
    )
    resolve_extraction(db, schema, 1, ext)
    e = db.list_entities("人物")[0]
    assert e["status"] == "pending_review"
    assert e["confidence"] < 0.7


def test_relation_events_three_states(tmp_path):
    """三态：首现记事件；同状态跳过；变化记新事件+刷新当前态。"""
    schema = load_config("config/novels/xuanjian.yaml")
    db = DB(str(tmp_path / "ev.db"))

    def _ext(attrs: dict) -> ChapterExtraction:
        return ChapterExtraction(
            entities=[
                ExtractedEntity(type="势力", name="李家", evidence="李家"),
                ExtractedEntity(type="势力", name="镜铁山", evidence="镜铁山"),
            ],
            relations=[
                ExtractedRelation(from_name="李家", to_name="镜铁山", type="势力关系",
                                  attrs=attrs, evidence="某章原文"),
            ],
        )

    # 状态1：首现 -> 记事件
    resolve_extraction(db, schema, 10, _ext({"性质": "附庸"}))
    assert len(db.list_relation_events()) == 1
    assert db.list_relations()[0]["attrs_json"] == '{"性质": "附庸"}'

    # 状态2：同 (type, attrs) 重复 -> 跳过，不产生新事件
    resolve_extraction(db, schema, 12, _ext({"性质": "附庸"}))
    assert len(db.list_relation_events()) == 1

    # 状态3：attrs 变化 -> 新事件 + relations 刷新（同 rid，chapter 更新）
    resolve_extraction(db, schema, 40, _ext({"性质": "敌对"}))
    events = db.list_relation_events()
    assert len(events) == 2
    rels = db.list_relations()
    assert len(rels) == 1
    assert rels[0]["attrs_json"] == '{"性质": "敌对"}'
    assert rels[0]["chapter"] == 40

    # as_of 语义：30 章时应是附庸
    as_of = [r for r in db.relations_as_of(30)
             if r["from_id"] == rels[0]["from_id"]]
    assert as_of[0]["attrs_json"] == '{"性质": "附庸"}'


def test_relation_type_change_replaces_old_edge(tmp_path):
    """同一对实体关系 type 变化时，relations 旧行被替换（每对至多一条当前边）。"""
    schema = load_config("config/novels/xuanjian.yaml")
    db = DB(str(tmp_path / "ev3.db"))

    ext_a = ChapterExtraction(
        entities=[
            ExtractedEntity(type="人物", name="甲", evidence="x"),
            ExtractedEntity(type="势力", name="李家", evidence="x"),
        ],
        relations=[ExtractedRelation(from_name="甲", to_name="李家", type="所属",
                                     evidence="x")],
    )
    resolve_extraction(db, schema, 5, ext_a)
    assert len(db.list_relations()) == 1

    # 同一对改成"关系"类型（type 变化）：旧行删除，只留新行
    ext_b = ChapterExtraction(
        entities=[],
        relations=[ExtractedRelation(from_name="甲", to_name="李家", type="关系",
                                     attrs={"关系": "供奉"}, evidence="x")],
    )
    resolve_extraction(db, schema, 8, ext_b)
    rels = db.list_relations()
    assert len(rels) == 1
    assert rels[0]["type"] == "关系"
    # 事件流完整保留两段历史
    assert len(db.list_relation_events()) == 2


def test_multi_key_attrs_repeat_no_extra_event(tmp_path):
    """多键 attrs（键序≠字典序）重复出现：存入与比较都用规范化串，不误判变化。"""
    schema = load_config("config/novels/xuanjian.yaml")
    db = DB(str(tmp_path / "mk.db"))

    def _ext(attrs: dict) -> ChapterExtraction:
        return ChapterExtraction(
            entities=[
                ExtractedEntity(type="势力", name="甲宗", evidence="x"),
                ExtractedEntity(type="势力", name="乙门", evidence="x"),
            ],
            relations=[ExtractedRelation(from_name="甲宗", to_name="乙门",
                                         type="势力关系", attrs=attrs, evidence="x")],
        )

    # 两次同 attrs 但构造时键序不同（dict 插入序不同）
    resolve_extraction(db, schema, 5, _ext({"性质": "盟友", "强度": "稳固"}))
    resolve_extraction(db, schema, 9, _ext({"强度": "稳固", "性质": "盟友"}))
    assert len(db.list_relation_events()) == 1  # 无冗余事件
    assert len(db.list_relations()) == 1
    # relations 表里的 attrs_json 是规范化（sort_keys）形式
    assert db.list_relations()[0]["attrs_json"] == '{"强度": "稳固", "性质": "盟友"}'


def test_replay_old_chapter_no_inflation(tmp_path):
    """重放场景：库中已有后续章节事件时，重放早期章不得因全局 latest 错位而膨胀。"""
    schema = load_config("config/novels/xuanjian.yaml")
    db = DB(str(tmp_path / "rp.db"))

    def _ext(ch: int, attrs: dict) -> ChapterExtraction:
        return ChapterExtraction(
            entities=[
                ExtractedEntity(type="人物", name="甲", evidence="x"),
                ExtractedEntity(type="人物", name="乙", evidence="x"),
            ],
            relations=[ExtractedRelation(from_name="甲", to_name="乙", type="关系",
                                         attrs=attrs, evidence="x")],
        )

    # 逐章跑到 60 章：父子 → 师徒（两次变化）
    resolve_extraction(db, schema, 3, _ext(3, {"关系": "父子"}))
    resolve_extraction(db, schema, 21, _ext(21, {"关系": "父子"}))
    resolve_extraction(db, schema, 60, _ext(60, {"关系": "师徒"}))
    n_events = len(db.list_relation_events())
    assert n_events == 2  # 首现 + 师徒变化；21 章同状态跳过

    # 重放第 3 章（pipeline 每次全量重放会走到）：不得新增事件
    resolve_extraction(db, schema, 3, _ext(3, {"关系": "父子"}))
    assert len(db.list_relation_events()) == n_events

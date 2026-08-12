import json
from novel_kg.store import DB


def test_store_roundtrip_chapters_extractions_entities_relations(tmp_path):
    db = DB(str(tmp_path / "t.db"))

    # 章节
    db.upsert_chapter(1, "第一章", "正文……")
    assert db.get_chapter(1)["title"] == "第一章"

    # 原始抽取 + 断点续传
    db.save_extraction(1, '{"entities":[],"relations":[]}')
    assert db.has_extraction(1) is True
    assert db.has_extraction(2) is False

    # 实体 + 别名 + 查找
    db.upsert_entity("人物_1", "人物", "林动", "人物_1",
                     json.dumps({"境界": "元力"}, ensure_ascii=False), 1, 0.9, "confirmed")
    db.add_alias("人物_1", "动哥")
    assert db.find_entity_id("人物", "林动") == "人物_1"
    assert db.find_entity_id("人物", "动哥") == "人物_1"
    assert db.find_entity_id_any("动哥") == "人物_1"

    # 分类
    db.add_classification("人物_1", "阵营", "青阳镇")
    rows = db.list_classifications("人物_1")
    assert {"dimension": "阵营", "value": "青阳镇"} in rows

    # 关系
    db.upsert_entity("势力_1", "势力", "青阳镇", "势力_1", "{}", 1, 0.9, "confirmed")
    db.upsert_relation("rel_1", "人物_1", "势力_1", "所属", "{}", 1, "林动家住青阳镇")
    rels = db.list_relations()
    assert len(rels) == 1 and rels[0]["type"] == "所属"

    # 统计
    counts = {r["type"]: r["n"] for r in db.entity_counts()}
    assert counts["人物"] == 1 and counts["势力"] == 1

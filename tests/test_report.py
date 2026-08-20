import json
from novel_kg.report import generate_report
from novel_kg.store import DB


def test_report_contains_counts_and_entities(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    db.upsert_entity("人物_1", "人物", "林动", "人物_1",
                     json.dumps({"境界": "元力"}, ensure_ascii=False), 1, 0.9, "confirmed")
    db.upsert_entity("势力_1", "势力", "青阳镇", "势力_1", "{}", 1, 0.9, "confirmed")
    db.upsert_relation("rel_1", "人物_1", "势力_1", "所属", "{}", 1, "林动家住青阳镇")

    md = generate_report(db)

    assert "# 小说分析报告" in md
    assert "林动" in md
    assert "青阳镇" in md
    assert "所属" in md


def test_report_shows_specific_relation_not_generic(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    db.upsert_entity("人物_1", "人物", "李项平", "人物_1", "{}", 1, 0.9, "confirmed")
    db.upsert_entity("人物_2", "人物", "李木田", "人物_2", "{}", 1, 0.9, "confirmed")
    db.upsert_relation("rel_1", "人物_1", "人物_2", "关系",
                       '{"关系": "父子"}', 1, "阿爹")
    md = generate_report(db)
    assert "父子" in md            # 显示具体关系
    assert "--关系--" not in md    # 不再只写"关系"两个字

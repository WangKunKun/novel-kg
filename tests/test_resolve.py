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

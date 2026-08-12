from novel_kg.models import ChapterExtraction, ExtractedEntity, ExtractedRelation


def test_chapter_extraction_parses_entities_and_relations():
    raw = {
        "entities": [
            {"type": "人物", "name": "林动", "aliases": ["动哥"],
             "classifications": {}, "attrs": {"境界": "元力"}, "evidence": "林动凝气成功"}
        ],
        "relations": [
            {"from_name": "林动", "to_name": "青阳镇", "type": "所属",
             "attrs": {}, "evidence": "林动家住青阳镇"}
        ],
    }
    ext = ChapterExtraction.model_validate(raw)
    assert isinstance(ext.entities[0], ExtractedEntity)
    assert ext.entities[0].aliases == ["动哥"]
    assert isinstance(ext.relations[0], ExtractedRelation)

from novel_kg.config import load_config
from novel_kg.extract import extract_chapter
from novel_kg.ingest import Chapter
from novel_kg.llm_client import FakeLLMClient


def test_extract_chapter_parses_llm_json_into_models():
    schema = load_config("config/novels/xuanjian.yaml")
    fake = FakeLLMClient(
        response={
            "entities": [
                {"type": "仙基", "name": "玄水仙基",
                 "aliases": [], "classifications": {"五行": "水", "品阶": "仙品"},
                 "attrs": {"作用": "凝水成兵"}, "evidence": "他修成玄水仙基"}
            ],
            "relations": [
                {"from_name": "林动", "to_name": "玄水仙基", "type": "修炼",
                 "attrs": {}, "evidence": "林动修炼玄水仙基"}
            ],
        }
    )
    chapter = Chapter(1, "第一章 试炼", "林动修炼玄水仙基……")

    ext = extract_chapter(fake, schema, chapter)

    assert len(ext.entities) == 1
    assert ext.entities[0].classifications["五行"] == "水"
    assert len(ext.relations) == 1
    assert ext.relations[0].type == "修炼"
    # prompt 里应包含 taxonomy 可选值，确保模型按规范分类
    assert "金" in fake.calls[0][0] and "仙品" in fake.calls[0][0]

from novel_kg.llm_client import FakeLLMClient
from novel_kg.pipeline import run_pipeline


SAMPLE = """第一章 初入江湖
林动走进了森林。

第二章 初露锋芒
林动挥拳打退了妖兽。
"""


def test_pipeline_end_to_end_with_fake_llm(tmp_path):
    novel = tmp_path / "book.txt"
    novel.write_text(SAMPLE, encoding="utf-8")
    db_path = str(tmp_path / "t.db")

    fake = FakeLLMClient(
        response={
            "entities": [
                {"type": "人物", "name": "林动", "aliases": [],
                 "classifications": {}, "attrs": {}, "evidence": "林动走进森林"}
            ],
            "relations": [],
        }
    )
    db = run_pipeline(
        novel_path=str(novel),
        schema_path="config/novels/xuanjian.yaml",
        db_path=db_path,
        client=fake,
    )

    # 两次章节都被抽取
    assert db.has_extraction(1) and db.has_extraction(2)
    # 人物被归并成同一个（两章都叫林动）
    assert len(db.list_entities("人物")) == 1
    assert db.get_chapter(2)["title"].startswith("第二章")


def test_pipeline_resumes_skipping_extracted_chapters(tmp_path):
    novel = tmp_path / "book.txt"
    novel.write_text(SAMPLE, encoding="utf-8")
    db_path = str(tmp_path / "t.db")

    fake = FakeLLMClient(
        response={"entities": [], "relations": []}
    )
    # 第一次跑
    run_pipeline(str(novel), "config/novels/xuanjian.yaml", db_path, fake)
    first_calls = len(fake.calls)
    # 第二次跑：应复用已有抽取，不再调用 LLM
    run_pipeline(str(novel), "config/novels/xuanjian.yaml", db_path, fake)
    assert len(fake.calls) == first_calls

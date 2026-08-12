from novel_kg.ingest import read_novel


SAMPLE = """简介：这是一本小说。

第一章 初入江湖
林动走进了森林。
他遇见了一只妖兽。

第二章 初露锋芒
林动挥拳打退了妖兽。
"""


def test_read_novel_splits_chapters_and_skips_preamble(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text(SAMPLE, encoding="utf-8")
    chapters = read_novel(str(p))
    assert len(chapters) == 2
    assert chapters[0].index == 1
    assert chapters[0].title.startswith("第一章")
    assert "林动走进了森林" in chapters[0].text
    assert "简介" not in chapters[0].text  # 前言被跳过
    assert chapters[1].index == 2
    assert "挥拳" in chapters[1].text

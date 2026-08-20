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


EQUALS_SAMPLE = """《玄鉴仙族》
来源:https://example.org
本文件仅供个人学习阅读。

========================================

====== 第1章 初入 ======
陆江仙做了一个很长很长的梦，梦见仙宗。
他醒来了。

====== 第2章 李家 ======
李家是镇上的大户。
"""


def test_read_novel_handles_equals_wrapped_chapter_titles(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text(EQUALS_SAMPLE, encoding="utf-8")
    chapters = read_novel(str(p))
    assert len(chapters) == 2
    assert chapters[0].index == 1
    assert "第1章" in chapters[0].title
    assert "初入" in chapters[0].title
    assert "做了一个很长很长的梦" in chapters[0].text
    assert "来源" not in chapters[0].text  # 前言被跳过
    assert "====== 第2章" not in chapters[0].text  # 下一章标题不串进本章
    assert chapters[1].index == 2
    assert "李家" in chapters[1].text


EQUALS_WITH_NOISE_SAMPLE = """====== 第1章 初入 ======
陆江仙做了一个梦。
他醒来了。

第三百一十章 散修（加更说明）

====== 第2章 后续 ======
正文继续。
"""


def test_read_novel_ignores_bare_chapter_markers_when_equals_wrapped_exist(tmp_path):
    # 正文中独立成行的裸"第X章"（如加更说明、卷尾语）不应被切成章节：
    # 只要文件里有等号包裹的标题，就只认等号标题
    p = tmp_path / "book.txt"
    p.write_text(EQUALS_WITH_NOISE_SAMPLE, encoding="utf-8")
    chapters = read_novel(str(p))
    assert len(chapters) == 2  # 不是 3：裸"第三百一十章"是第1章正文
    assert "第三百一十章" in chapters[0].text  # 裸引用归入正文
    assert "加更说明" in chapters[0].text
    assert chapters[1].title.startswith("====== 第2章")

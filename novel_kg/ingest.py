import re
from dataclasses import dataclass

# 匹配 "第一章 ..."、"第3章 ..."、"第一百二十回 ..." 等
CHAPTER_RE = re.compile(
    r"^\s*第[零一二三四五六七八九十百千万0-9]+[章节回卷][\s:：、\.]*.*$"
)


@dataclass
class Chapter:
    index: int   # 从 1 开始的章节号
    title: str
    text: str


def read_novel(path: str) -> list[Chapter]:
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    chapters: list[Chapter] = []
    cur_title: str | None = None
    cur_lines: list[str] = []

    for line in lines:
        if CHAPTER_RE.match(line.strip()):
            if cur_title is not None:
                chapters.append(
                    Chapter(len(chapters) + 1, cur_title, "\n".join(cur_lines).strip())
                )
            cur_title = line.strip()
            cur_lines = []
        elif cur_title is not None:
            cur_lines.append(line)

    if cur_title is not None:
        chapters.append(
            Chapter(len(chapters) + 1, cur_title, "\n".join(cur_lines).strip())
        )
    return chapters

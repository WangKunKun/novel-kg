import re
from dataclasses import dataclass

# 带等号包裹的标题："====== 第1章 初入 ======"（前导至少一个等号）
EQUALS_CHAPTER_RE = re.compile(
    r"^\s*=+\s*第[零一二三四五六七八九十百千万0-9]+[章节回卷][\s:：、\.]*.*$"
)
# 裸标题："第一章 ..."、"第3章 ..."、"第一百二十回 ..." 等
BARE_CHAPTER_RE = re.compile(
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

    # 文件级自适应：若存在等号包裹的标题，就只用它切分，避免正文中
    # 独立成行的裸"第X章"（如加更说明、卷尾语）被误切成章节；
    # 否则回退到裸标题正则。
    use_equals = any(EQUALS_CHAPTER_RE.match(l.strip()) for l in lines)
    chapter_re = EQUALS_CHAPTER_RE if use_equals else BARE_CHAPTER_RE

    chapters: list[Chapter] = []
    cur_title: str | None = None
    cur_lines: list[str] = []

    for line in lines:
        if chapter_re.match(line.strip()):
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

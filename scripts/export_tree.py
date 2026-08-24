"""族谱/师徒树导出 CLI。

用法：
    .venv/bin/python scripts/export_tree.py 族谱 [--db data/novel.db] [--out data/exports]
    .venv/bin/python scripts/export_tree.py 师徒 --faction 青池宗 [--db] [--out]

产出 {名称}.svg/.png/.md 三件套（dot 缺失时仅 .md 并提示），
多父/环/未定位等数据问题写入 {名称}.issues.md 供人工回查修库。
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from novel_kg.trees import (  # noqa: E402
    build_family_tree, build_master_tree, li_family_members, render_dot, render_mermaid,
)


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="族谱/师徒树导出")
    ap.add_argument("mode", choices=["族谱", "师徒"])
    ap.add_argument("--db", default="data/novel.db")
    ap.add_argument("--out", default="data/exports")
    ap.add_argument("--faction", help="师徒模式：势力名")
    args = ap.parse_args(argv)

    import sqlite3
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.mode == "族谱":
        members = li_family_members(conn)
        if not members:
            print("圈定为空：找不到李家种子成员", file=sys.stderr)
            return 1
        tree = build_family_tree(conn, members)
        name = "李氏族谱"
    else:
        if not args.faction:
            print("师徒模式需要 --faction 势力名", file=sys.stderr)
            return 1
        tree = build_master_tree(conn, args.faction)
        if tree.issues and tree.issues[-1].startswith("势力「"):
            print(tree.issues[-1], file=sys.stderr)
            return 1
        name = f"{args.faction}师徒"

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dot_src = render_dot(tree)
    (out_dir / f"{name}.md").write_text(
        f"# {tree.title}\n\n```mermaid\n{render_mermaid(tree)}\n```\n", encoding="utf-8")
    if shutil.which("dot"):
        for fmt in ("svg", "png"):
            subprocess.run(
                ["dot", f"-T{fmt}", "-o", str(out_dir / f"{name}.{fmt}")],
                input=dot_src.encode("utf-8"), check=True)
        print(f"已导出 {out_dir}/{name}.svg/.png/.md")
    else:
        print("未找到系统 dot，仅导出 Mermaid（brew install graphviz 可补图片）")
    if tree.issues:
        (out_dir / f"{name}.issues.md").write_text(
            f"# {tree.title} 数据问题\n\n" + "\n".join(f"- {i}" for i in tree.issues),
            encoding="utf-8")
        print(f"发现 {len(tree.issues)} 条数据问题，见 {name}.issues.md")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))

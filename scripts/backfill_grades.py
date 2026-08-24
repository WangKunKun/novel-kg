"""2026-08-24 一次性存量回填：功法品级/境界 + 势力顶尖战力。

依据（作者嵌正文的设定笔记 + 1137 行）："功法分为九品，一品最次，九品最好"；
功法境界=适用阶段（胎息/练气/直指筑基）。势力顶尖战力从"所属"边成员的
最高境界推断（宁缺毋滥：成员全无境界信息则不写，防低估误导）。

用法：
    .venv/bin/python scripts/backfill_grades.py data/novel.db [--dry-run]
"""
import json
import re
import sqlite3
import sys

sys.path.insert(0, ".")
from novel_kg.viz_app import person_rank  # noqa: E402

PIN_RE = re.compile(r"([一二三四五六七八九])品")

# 功法境界判定（优先级从上到下）：太阴吐纳养轮经类文本含"胎息"即胎息功法；
# "直指筑基/唯到筑基"为筑基向；其余含练气/炼气为练气功法
GONGFA_STAGE_RULES = [("胎息", "胎息"), ("筑基", "筑基"), ("练气", "练气"), ("炼气", "练气")]

# person_rank → 战力标签（与 viz FACTION_POWER 对齐）
RANK_TO_POWER = [(26, "金丹"), (24, "紫府"), (20, "筑基"), (10, "练气"), (1, "胎息")]


def rank_to_power(rk: int) -> str:
    for floor, label in RANK_TO_POWER:
        if rk >= floor:
            return label
    return ""


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 1) 功法：attrs 文本 → 品级分类 + 境界字段
    n_pin = n_stage = 0
    for row in conn.execute(
        "SELECT id, name, attrs_json FROM entities WHERE type='功法'"
    ).fetchall():
        attrs = json.loads(row["attrs_json"] or "{}")
        text = "；".join(str(v) for v in attrs.values() if v)
        m = PIN_RE.search(text)
        stage = next((s for kw, s in GONGFA_STAGE_RULES if kw in text), "")
        changed = False
        if m:
            if dry:
                print(f"  [品级] {row['name']} -> {m.group(1)}品")
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO classifications(entity_id,dimension,value) VALUES(?,?,?)",
                    (row["id"], "品级", f"{m.group(1)}品"),
                )
            n_pin += 1
            changed = True
        if stage and not attrs.get("境界"):
            if dry:
                print(f"  [境界] {row['name']} -> {stage}")
            else:
                attrs["境界"] = stage
                conn.execute(
                    "UPDATE entities SET attrs_json=? WHERE id=?",
                    (json.dumps(attrs, ensure_ascii=False), row["id"]),
                )
            n_stage += 1
            changed = True
    print(f"功法：品级 {n_pin}、境界 {n_stage}")

    # 2) 势力：成员最高境界 → 顶尖战力
    n_power = 0
    for fac in conn.execute(
        "SELECT id, name, attrs_json FROM entities WHERE type='势力'"
    ).fetchall():
        members = conn.execute(
            "SELECT from_id FROM relations WHERE type='所属' AND to_id=?", (fac["id"],)
        ).fetchall()
        best = 0
        for m in members:
            row = conn.execute(
                "SELECT attrs_json FROM entities WHERE id=?", (m["from_id"],)
            ).fetchone()
            if not row:
                continue
            jingjie = json.loads(row["attrs_json"] or "{}").get("境界", "")
            rk = person_rank(str(jingjie))
            best = max(best, rk)
        label = rank_to_power(best)
        attrs = json.loads(fac["attrs_json"] or "{}")
        if label and attrs.get("顶尖战力") != label:
            if dry:
                print(f"  [顶尖战力] {fac['name']} -> {label}（成员 {len(members)} 人）")
            else:
                attrs["顶尖战力"] = label
                conn.execute(
                    "UPDATE entities SET attrs_json=? WHERE id=?",
                    (json.dumps(attrs, ensure_ascii=False), fac["id"]),
                )
            n_power += 1
    print(f"势力：顶尖战力 {n_power}")
    if not dry:
        conn.commit()
        print("落库完成")


if __name__ == "__main__":
    main()

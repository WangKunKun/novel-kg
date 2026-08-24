"""2026-08-24 一次性存量修正：胎息轮从"仙基"拆出为独立"轮"类型。

概念纠偏（2026-08-20 fix_xianji.py 四拆时的遗留误判）：原文 8624 行
"练气化筑基最关键一步便是化去六轮，凝结为种种道基"——胎息六轮是第一境
（胎息）的产物，筑基时被化掉；筑基后凝结的道基（湖月秋/浩瀚海/应帝王）
才是仙基。故 10 个轮实体独立成"轮"类型。

同步改 raw_json 里这批实体的 type（防将来重放时按旧"仙基"类型回退）。

用法：
    .venv/bin/python scripts/split_taixi_lun.py data/novel.db [--dry-run]
"""
import json
import sqlite3
import sys

# 10 个胎息轮（玄景轮/周行轮/承明轮/玉京轮/青元轮 = 六轮本体；灵初轮/
# 气海灵轮 = 六轮别名层级；上琅灵轮/太阴六轮/白玉六轮 = 功法凝轮变体，
# 原文自证：上琅灵轮"依《上琅养轮诀》凝聚的胎息灵轮"、太阴六轮"原先
# 胎息功法所凝灵轮尽化为太阴六轮"、白玉六轮"《长锦问心诀》胎息篇练就"）
LUN_NAMES = [
    "玄景轮", "周行轮", "承明轮", "玉京轮", "青元轮",
    "灵初轮", "气海灵轮", "上琅灵轮", "太阴六轮", "白玉六轮",
]

# attrs 顺手修复（类型整理中发现的两处脏数据）
ATTRS_FIX = {
    # 玉京轮 attrs 混入势力字段（层级/立场/首领/简介"万萧华所属的修仙势力"，
    # 系历史合并迁移污染）：只保留轮语义字段
    "玉京轮": lambda a: {k: v for k, v in a.items()
                         if k in ("作用", "修炼者", "副作用")},
    # 白玉盘修炼者"李尺泾（于羽楔）"有误：9443 行"炼就了道基『白玉盘』"的是于羽楔
    # （双剑修士，死于南疆，被大蛟炼丹）；李尺泾筑基道基是湖月秋（8621 行）
    "白玉盘": lambda a: {**a, "修炼者": "于羽楔"},
}


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, name, type FROM entities WHERE name IN "
        f"('{ "','".join(LUN_NAMES) }') ORDER BY first_chapter"
    ).fetchall()
    print(f"待改型 {len(rows)}：")
    for r in rows:
        print(f"  {r['name']} [{r['type']}] -> 轮")

    raw_changed = 0
    for row in conn.execute("SELECT chapter, raw_json FROM extractions").fetchall():
        data = json.loads(row["raw_json"])
        changed = False
        for e in data.get("entities", []):
            if e.get("name") in LUN_NAMES and e.get("type") != "轮":
                e["type"] = "轮"
                changed = True
        if changed:
            raw_changed += 1
            if not dry:
                conn.execute(
                    "UPDATE extractions SET raw_json=? WHERE chapter=?",
                    (json.dumps(data, ensure_ascii=False), row["chapter"]),
                )
    print(f"raw_json 同步 {raw_changed} 章")

    if dry:
        return
    with conn:
        q = f"('{ "','".join(LUN_NAMES) }')"
        conn.execute(f"UPDATE entities SET type='轮' WHERE name IN {q}")
        for name, fix in ATTRS_FIX.items():
            row = conn.execute(
                "SELECT attrs_json FROM entities WHERE name=?", (name,)
            ).fetchone()
            if not row:
                print(f"  跳过 attrs 修复 {name}（实体缺失）")
                continue
            fixed = fix(json.loads(row["attrs_json"] or "{}"))
            conn.execute(
                "UPDATE entities SET attrs_json=? WHERE name=?",
                (json.dumps(fixed, ensure_ascii=False), name),
            )
            print(f"  修 attrs {name}")
    left = conn.execute(
        f"SELECT COUNT(*) c FROM entities WHERE name IN {q} AND type!='轮'"
    ).fetchone()["c"]
    print(f"落库完成，残留 {left}")


if __name__ == "__main__":
    main()

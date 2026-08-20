"""2026-08-20 合并同名不同 type 的双行实体（7 个，多为仙基四拆词汇的历史分叉）。

对每个名字：保留"正确 type"行，错误行的别名/分类/关系/attrs 迁移过去后删除，
并同步 extractions.raw_json 里的 type（否则 pipeline 重放会再建回来）。

用法：
    .venv/bin/python scripts/merge_dup_entities.py data/novel.db [--dry-run]
"""
import json
import sqlite3
import sys

sys.path.insert(0, "scripts")
from fix_xianji import NAME_TO_TYPE, rel_id

# 双行里非仙基来源的名字也要给正确 type；轮一律仙基
EXTRA_TRUTH = {
    "太阴玄光": "道具",   # 用户判定：气类突破资源
    "接引法": "功法",
    "月阙剑弧": "术法",
    "玄水剑诀": "功法",
    "玉京轮": "仙基",     # "势力"行明显错
    "祭萃夺元法": "术法",
    "金光术": "术法",
}


def truth_type(name: str) -> str:
    if name in EXTRA_TRUTH:
        return EXTRA_TRUTH[name]
    if name in NAME_TO_TYPE:
        return NAME_TO_TYPE[name]
    return "仙基" if name.endswith("轮") else None


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    dup_names = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM entities GROUP BY name HAVING COUNT(DISTINCT type)>1"
        )
    ]
    print(f"双行名字 {len(dup_names)} 个：{dup_names}")
    ops: list[tuple[str, str]] = []  # (bad_id, good_id)
    for name in dup_names:
        truth = truth_type(name)
        rows = conn.execute(
            "SELECT * FROM entities WHERE name=?", (name,)
        ).fetchall()
        good = [r for r in rows if r["type"] == truth]
        if truth is None or not good:
            print(f"  !! {name}: 无权威 type 或找不到正确行，跳过（{[r['type'] for r in rows]}）")
            continue
        good_id = good[0]["id"]
        for r in rows:
            if r["id"] != good_id:
                ops.append((r["id"], good_id))
                print(f"  {name}: 删 {r['type']}({r['id']}) -> 留 {truth}({good_id})")

    if dry:
        print("dry-run，不落库")
        return

    with conn:
        for bad_id, good_id in ops:
            # 1) 关系端点迁移 + 确定性 id 重算（同 resolve._rel_id，防重放插重复边）
            for r in conn.execute(
                "SELECT * FROM relations WHERE from_id=? OR to_id=?", (bad_id, bad_id)
            ).fetchall():
                new_from = good_id if r["from_id"] == bad_id else r["from_id"]
                new_to = good_id if r["to_id"] == bad_id else r["to_id"]
                new_id = rel_id(new_from, new_to, r["type"])
                hit = conn.execute(
                    "SELECT 1 FROM relations WHERE id=?", (new_id,)
                ).fetchone()
                if hit:
                    conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                else:
                    conn.execute(
                        "UPDATE relations SET id=?, from_id=?, to_id=? WHERE id=?",
                        (new_id, new_from, new_to, r["id"]),
                    )
            # 2) 别名/分类迁移
            for a in conn.execute(
                "SELECT alias FROM aliases WHERE entity_id=?", (bad_id,)
            ).fetchall():
                conn.execute(
                    "INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)",
                    (good_id, a["alias"]),
                )
            for c in conn.execute(
                "SELECT dimension,value FROM classifications WHERE entity_id=?",
                (bad_id,),
            ).fetchall():
                conn.execute(
                    "INSERT OR IGNORE INTO classifications(entity_id,dimension,value) VALUES(?,?,?)",
                    (good_id, c["dimension"], c["value"]),
                )
            # 3) attrs 合并（不覆盖已有键）
            bad = conn.execute("SELECT attrs_json FROM entities WHERE id=?", (bad_id,)).fetchone()
            good = conn.execute("SELECT attrs_json FROM entities WHERE id=?", (good_id,)).fetchone()
            try:
                merged = {**json.loads(bad["attrs_json"] or "{}"),
                          **json.loads(good["attrs_json"] or "{}")}
                conn.execute(
                    "UPDATE entities SET attrs_json=? WHERE id=?",
                    (json.dumps(merged, ensure_ascii=False), good_id),
                )
            except json.JSONDecodeError:
                pass
            # 4) 删错误行
            conn.execute("DELETE FROM entities WHERE id=?", (bad_id,))
            conn.execute("DELETE FROM aliases WHERE entity_id=?", (bad_id,))
            conn.execute("DELETE FROM classifications WHERE entity_id=?", (bad_id,))

        # 5) raw_json 同步：错误 type 的同名实体改成正确 type；
        #    四类指向型关系的 type 按端点实体最终 type 校正（如 施展->道具 改 持有）
        from fix_xianji import REL_BY_TO_TYPE

        name_to_final_type = {
            r["name"]: r["type"] for r in conn.execute("SELECT name, type FROM entities")
        }
        for row in conn.execute("SELECT chapter, raw_json FROM extractions").fetchall():
            data = json.loads(row["raw_json"])
            dirty = False
            for e in data.get("entities", []):
                if e.get("type") != "人物" and truth_type(e.get("name", "")) not in (None, e.get("type")):
                    e["type"] = truth_type(e["name"])
                    dirty = True
            for r in data.get("relations", []):
                if r.get("type") in REL_BY_TO_TYPE.values() and r.get("type") != "修炼":
                    final = name_to_final_type.get(r.get("to_name", ""))
                    if final in REL_BY_TO_TYPE and REL_BY_TO_TYPE[final] != r["type"]:
                        r["type"] = REL_BY_TO_TYPE[final]
                        dirty = True
                elif r.get("type") == "修炼":
                    final = name_to_final_type.get(r.get("to_name", ""))
                    if final in REL_BY_TO_TYPE and final != "功法":
                        r["type"] = REL_BY_TO_TYPE[final]
                        dirty = True
            if dirty:
                conn.execute(
                    "UPDATE extractions SET raw_json=? WHERE chapter=?",
                    (json.dumps(data, ensure_ascii=False), row["chapter"]),
                )
    print("落库完成")
    for row in conn.execute(
        "SELECT COUNT(*) c FROM (SELECT name FROM entities GROUP BY name HAVING COUNT(DISTINCT type)>1)"
    ):
        print(f"  剩余双行: {row['c']}")


if __name__ == "__main__":
    main()

"""2026-08-21 通用别名碎片合并脚本（每批章节跑完后的人工核查修正）。

MERGE（碎片名 → 目标名）：别名/分类/关系/事件全部迁移到目标实体，
碎片名写入目标 aliases（重放时别名机制自动归并，raw_json 无需改写）。
RENAME（旧名 → 新名）：无目标实体的改名（如简称先建了实体），改名后
新旧名都写入 aliases，重放两侧都能归并。

用法：
    .venv/bin/python scripts/merge_alias_fragments.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys

# 2026-08-21 批次（76-100 章）人工核查结论：
# - 羽楔/于羽楔：同一人，81章司元白"羽楔被派去凑太阴月华"= 87章"筑基修士于羽楔吞服太阴月华战死倚山城"
# - 玄岭/李玄岭：同一人，91-96章两词同频共现，93章"玄岭"为单独简称
# - 漆黑长弓/黝黑长弓：同一把弓（李玄锋），84章"黝黑的长弓"= 94章"漆黑长弓"
# - 金丹黄箓/黄箓：同一枚箓，95章"远方大山深处的黄箓(金丹级)"= 96章"大厥庭方向那枚金丹黄箓"；
#   主名取"黄箓"与既有"灰箓"（箓气灰白青黄对应练气筑基紫府金丹）命名风格一致
# - 箓气/灰箓：同一枚，97章"李项平受的箓气避死延生"= 85章凝出赐下的灰箓
MERGE = {
    "羽楔": "于羽楔",
    "玄岭": "李玄岭",
    "漆黑长弓": "黝黑长弓",
    "金丹黄箓": "黄箓",
    "箓气": "灰箓",
}
# 黎山(78) 是"黎泾山"口语简称（原文两词混用指同一座山），库中无黎泾山实体，改名建主名
RENAME = {
    "黎山": "黎泾山",
}


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    key = f"{from_id}|{to_id}|{type_}"
    return f"rel_{hashlib.md5(key.encode()).hexdigest()[:12]}"


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    def eid(name: str) -> str | None:
        row = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
        return row["id"] if row else None

    def migrate(bad: str, good: str) -> None:
        """把 bad 实体的关系/事件/别名/分类/attrs 全部迁到 good，删 bad 行。"""
        for r in conn.execute(
            "SELECT * FROM relations WHERE from_id=? OR to_id=?", (bad, bad)
        ).fetchall():
            nf = good if r["from_id"] == bad else r["from_id"]
            nt = good if r["to_id"] == bad else r["to_id"]
            nid = rel_id(nf, nt, r["type"])
            hit = conn.execute("SELECT 1 FROM relations WHERE id=?", (nid,)).fetchone()
            if hit:
                conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
            else:
                conn.execute(
                    "UPDATE relations SET id=?, from_id=?, to_id=? WHERE id=?",
                    (nid, nf, nt, r["id"]),
                )
        conn.execute("UPDATE relation_events SET from_id=? WHERE from_id=?", (good, bad))
        conn.execute("UPDATE relation_events SET to_id=? WHERE to_id=?", (good, bad))
        for a in conn.execute("SELECT alias FROM aliases WHERE entity_id=?", (bad,)).fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)", (good, a["alias"])
            )
        for c in conn.execute(
            "SELECT dimension,value FROM classifications WHERE entity_id=?", (bad,)
        ).fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO classifications(entity_id,dimension,value) VALUES(?,?,?)",
                (good, c["dimension"], c["value"]),
            )
        b_attrs = json.loads(
            conn.execute("SELECT attrs_json FROM entities WHERE id=?", (bad,))
            .fetchone()["attrs_json"]
            or "{}"
        )
        g_json = conn.execute("SELECT attrs_json FROM entities WHERE id=?", (good,)).fetchone()[
            "attrs_json"
        ]
        merged = {**b_attrs, **json.loads(g_json or "{}")}
        conn.execute(
            "UPDATE entities SET attrs_json=? WHERE id=?",
            (json.dumps(merged, ensure_ascii=False), good),
        )
        conn.execute("DELETE FROM entities WHERE id=?", (bad,))
        conn.execute("DELETE FROM aliases WHERE entity_id=?", (bad,))
        conn.execute("DELETE FROM classifications WHERE entity_id=?", (bad,))

    plan_merge = []
    for frag, target in MERGE.items():
        b, g = eid(frag), eid(target)
        if b and g and b != g:
            plan_merge.append((frag, b, target, g))
        else:
            print(f"  跳过 {frag}（碎片/目标缺失或同 id）")

    plan_rename = []
    for old, new in RENAME.items():
        o = eid(old)
        if o and eid(new) is None:
            plan_rename.append((old, o, new))
        else:
            print(f"  跳过改名 {old}（缺失或新名已存在）")

    print(f"待合并 {len(plan_merge)}：{[(f, t) for f, _, t, _ in plan_merge]}")
    print(f"待改名 {len(plan_rename)}：{[(o, n) for o, _, n in plan_rename]}")
    if dry:
        return

    with conn:
        for frag, bad, target, good in plan_merge:
            # 碎片名入目标 aliases（重放归并的关键），先加再迁（别名随迁不丢）
            conn.execute("INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)", (good, frag))
            migrate(bad, good)
            print(f"  合并 {frag} -> {target}")
        for old, bad, new in plan_rename:
            conn.execute("UPDATE entities SET name=? WHERE id=?", (new, bad))
            conn.execute("INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)", (bad, new))
            conn.execute("INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)", (bad, old))
            print(f"  改名 {old} -> {new}")
    print("落库完成")

    names = list(MERGE) + list(MERGE.values()) + list(RENAME) + list(RENAME.values())
    q = "('" + "','".join(names) + "')"
    for row in conn.execute(f"SELECT name, type, first_chapter FROM entities WHERE name IN {q}"):
        print(f"  {row['name']} [{row['type']}] 首现{row['first_chapter']}章")
    left = conn.execute(
        f"SELECT COUNT(*) c FROM entities WHERE name IN ('" + "','".join(MERGE) + "')"
    ).fetchone()["c"]
    print(f"  碎片残留: {left}")


if __name__ == "__main__":
    main()

"""2026-08-20 合并势力称谓碎片实体 + 删除泛指实体。

合并（碎片名 → 目标名）：别名/分类/关系/事件全部迁移到目标实体，
碎片名写入目标 aliases（重放时别名机制自动归并，raw_json 无需改写）。
删除（泛指名）：实体+关系+事件删除，并从 raw_json 剔除相关条目（防重放复活）。

用法：
    .venv/bin/python scripts/merge_faction_fragments.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys

MERGE = {
    "黎泾李家": "李家",
    "泾阳柳家": "柳家",
    "青池": "青池宗",
    "仙宗": "青池宗",
}
DELETE = ["世家大族", "诸村"]


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

    plan_merge = []
    for frag, target in MERGE.items():
        b, g = eid(frag), eid(target)
        if b and g and b != g:
            plan_merge.append((frag, b, target, g))
        else:
            print(f"  跳过 {frag}（碎片/目标不存在或相同）")

    plan_del = [(n, eid(n)) for n in DELETE if eid(n)]
    print(f"待合并 {len(plan_merge)} 个：{[(f, t) for f, _, t, _ in plan_merge]}")
    print(f"待删除 {len(plan_del)} 个：{[n for n, _ in plan_del]}")
    if dry:
        return

    with conn:
        for frag, bad, target, good in plan_merge:
            # 关系端点迁移 + 确定性 id 重算
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
            # 事件端点迁移（时间线信息不丢；rid 保留原值仅作关联标记）
            conn.execute("UPDATE relation_events SET from_id=? WHERE from_id=?", (good, bad))
            conn.execute("UPDATE relation_events SET to_id=? WHERE to_id=?", (good, bad))
            # 别名迁移 + 碎片名入目标 aliases（重放归并的关键）
            conn.execute("INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)", (good, frag))
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
            # attrs 合并（不覆盖已有键）
            b_attrs = json.loads(
                conn.execute("SELECT attrs_json FROM entities WHERE id=?", (bad,)).fetchone()["attrs_json"] or "{}"
            )
            g_row = conn.execute("SELECT attrs_json FROM entities WHERE id=?", (good,)).fetchone()
            merged = {**b_attrs, **json.loads(g_row["attrs_json"] or "{}")}
            conn.execute(
                "UPDATE entities SET attrs_json=? WHERE id=?",
                (json.dumps(merged, ensure_ascii=False), good),
            )
            # 删碎片行
            conn.execute("DELETE FROM entities WHERE id=?", (bad,))
            conn.execute("DELETE FROM aliases WHERE entity_id=?", (bad,))
            conn.execute("DELETE FROM classifications WHERE entity_id=?", (bad,))
            print(f"  合并 {frag} -> {target}")

        # 删除泛指：实体+关系+事件+raw_json 条目（防重放复活）
        for name, bad in plan_del:
            conn.execute("DELETE FROM relations WHERE from_id=? OR to_id=?", (bad, bad))
            conn.execute("DELETE FROM relation_events WHERE from_id=? OR to_id=?", (bad, bad))
            conn.execute("DELETE FROM entities WHERE id=?", (bad,))
            conn.execute("DELETE FROM aliases WHERE entity_id=?", (bad,))
            conn.execute("DELETE FROM classifications WHERE entity_id=?", (bad,))
            print(f"  删除 {name}")
        for row in conn.execute("SELECT chapter, raw_json FROM extractions").fetchall():
            data = json.loads(row["raw_json"])
            ents = [e for e in data.get("entities", []) if e.get("name") not in DELETE]
            rels = [
                r for r in data.get("relations", [])
                if r.get("from_name") not in DELETE and r.get("to_name") not in DELETE
            ]
            if len(ents) != len(data.get("entities", [])) or len(rels) != len(data.get("relations", [])):
                data["entities"], data["relations"] = ents, rels
                conn.execute(
                    "UPDATE extractions SET raw_json=? WHERE chapter=?",
                    (json.dumps(data, ensure_ascii=False), row["chapter"]),
                )
    print("落库完成")

    for row in conn.execute(
        "SELECT type, COUNT(*) n FROM entities GROUP BY type ORDER BY n DESC"
    ):
        print(f"  {row['type']}: {row['n']}")
    frag_left = conn.execute(
        "SELECT COUNT(*) c FROM entities WHERE name IN ('" + "','".join(MERGE) + "')"
    ).fetchone()["c"]
    print(f"  碎片残留: {frag_left}")


if __name__ == "__main__":
    main()

"""2026-08-20 一次性迁移：「敌对」→「势力关系」（attrs 补性质），raw_json 同步。

幂等：跑过一次后 WHERE type='敌对' 查不到即空转。
用法：
    .venv/bin/python scripts/migrate_relation_events.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    """与 resolve._rel_id 一致（md5 前 12 位），保证重放幂等。"""
    key = f"{from_id}|{to_id}|{type_}"
    return f"rel_{hashlib.md5(key.encode()).hexdigest()[:12]}"


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT * FROM relations WHERE type='敌对'").fetchall()
    print(f"敌对关系 {len(rows)} 条待迁移")
    if dry:
        for r in rows:
            print(f"  {r['from_id']} -敌对-> {r['to_id']} 将改为 势力关系(性质:敌对)")
        print("dry-run，不落库")
        return

    with conn:
        for r in rows:
            # attrs 合并补性质（保留既有键）
            attrs = json.loads(r["attrs_json"] or "{}")
            attrs.setdefault("性质", "敌对")
            attrs_json = json.dumps(attrs, ensure_ascii=False)
            new_id = rel_id(r["from_id"], r["to_id"], "势力关系")
            hit = conn.execute("SELECT 1 FROM relations WHERE id=?", (new_id,)).fetchone()
            if hit:
                conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
            else:
                conn.execute(
                    "UPDATE relations SET id=?, type=?, attrs_json=? WHERE id=?",
                    (new_id, "势力关系", attrs_json, r["id"]),
                )
        # raw_json 同步：relations[].type 敌对 -> 势力关系 + attrs 补性质
        for row in conn.execute("SELECT chapter, raw_json FROM extractions").fetchall():
            data = json.loads(row["raw_json"])
            dirty = False
            for r in data.get("relations", []):
                if r.get("type") == "敌对":
                    r["type"] = "势力关系"
                    attrs = r.get("attrs") or {}
                    attrs.setdefault("性质", "敌对")
                    r["attrs"] = attrs
                    dirty = True
            if dirty:
                conn.execute(
                    "UPDATE extractions SET raw_json=? WHERE chapter=?",
                    (json.dumps(data, ensure_ascii=False), row["chapter"]),
                )
    print("落库完成")
    for row in conn.execute(
        "SELECT type, COUNT(*) n FROM relations GROUP BY type ORDER BY n DESC"
    ):
        print(f"  {row['type']}: {row['n']}")


if __name__ == "__main__":
    main()

"""2026-08-26 一次性修正：安鹧言之女"安氏"实体错建为势力"安家"挂亲属边。

ch415"「安氏见过前辈。」…这是安鹧言之女，也是李曦明的新妻，算是他的嫂子"——
LLM 把人物端点写成"安家"（势力），致 3 条亲属边端点类型非法，族谱 BFS 撞 KeyError：
- 李曦明→安家 夫妻 (ch497"明公子夫人是…「安氏。」")
- 李曦峻→安家 叔嫂 (ch415"算是他的嫂子")
- 安家→安鹧言 父女 (ch415"安鹧言之女"；且原方向反，规范为父→女)

修法：建人物实体"安氏"（全书未具名，以原文自称"安氏"为名，循批次4"未具名
具体角色"例但族谱需要节点故建实体），3 边改挂 + 父女换向，
raw_json 同步改写（防重放复活）。

用法：
    .venv/bin/python scripts/fix_an_shi.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    return f"rel_{hashlib.md5(f'{from_id}|{to_id}|{type_}'.encode()).hexdigest()[:12]}"


def eid(conn, name):
    row = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
    return row["id"] if row else None


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    anjia = eid(conn, "安家")
    ximing, xijun, zhiyan = eid(conn, "李曦明"), eid(conn, "李曦峻"), eid(conn, "安鹧言")
    assert anjia and ximing and xijun and zhiyan, "依赖实体缺失，先跑批次清理"

    try:
        anshi = eid(conn, "安氏")
        if not anshi:
            anshi = "人物_" + hashlib.md5("人物|安氏".encode()).hexdigest()[:8]
            conn.execute(
                "INSERT INTO entities(id, type, name, attrs_json, first_chapter, confidence)"
                " VALUES(?,?,?,?,?,?)",
                (anshi, "人物", "安氏",
                 json.dumps({"所属势力": "安家", "简介":
                  "安鹧言之女（全书未具名，自称安氏），李曦明之妻，李曦峻称嫂子",
                  "境界": "", "师承": ""}, ensure_ascii=False),
                 415, 0.9))
            print(f"建实体 安氏 {anshi}")
        else:
            print(f"安氏已存在 {anshi}")

        # (旧边定位, 新边)——旧边按 (端点含安家, kind, chapter) 找；新边方向：父女=安鹧言→安氏
        plan = [
            (("李曦明", "安家", "夫妻", 497), ("李曦明", "安氏", "夫妻", 497)),
            (("李曦峻", "安家", "叔嫂", 415), ("李曦峻", "安氏", "叔嫂", 415)),
            (("安家", "安鹧言", "父女", 415), ("安鹧言", "安氏", "父女", 415)),
        ]
        name2id = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM entities")}
        for (of, ot, kind, och), (nf, nt, _, nch) in plan:
            old_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM relations WHERE type='关系' AND attrs_json LIKE ?"
                " AND chapter=? AND ((from_id=? AND to_id=?) OR (from_id=? AND to_id=?))",
                (f'%{kind}%', och, name2id[of], name2id[ot], name2id[ot], name2id[of]))]
            nid = rel_id(name2id[nf], name2id[nt], "关系")
            if conn.execute("SELECT 1 FROM relations WHERE id=?", (nid,)).fetchone():
                print(f"  跳过 {nf}→{nt} {kind}（已存在）")
            else:
                attrs = json.dumps({"关系": kind}, ensure_ascii=False)
                ev = {"夫妻": "「老夫多问一句？明公子夫人是…」「安氏。」",
                      "叔嫂": "这是安鹧言之女，也是李曦明的新妻，算是他的嫂子",
                      "父女": "这是安鹧言之女"}[kind]
                conn.execute(
                    "INSERT INTO relations(id, from_id, to_id, type, attrs_json, chapter, evidence)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (nid, name2id[nf], name2id[nt], "关系", attrs, nch, ev))
                conn.execute(
                    "INSERT INTO relation_events(rid, from_id, to_id, type, attrs_json, chapter,"
                    " evidence) VALUES(?,?,?,?,?,?,?)",
                    (nid, name2id[nf], name2id[nt], "关系", attrs, nch, ev))
                print(f"  补边 {nf}→{nt} {kind} (ch{nch})")
            for oid in old_ids:
                conn.execute("DELETE FROM relation_events WHERE rid=?", (oid,))
                conn.execute("DELETE FROM relations WHERE id=?", (oid,))
                print(f"  删旧边 {of}—{ot} {kind} ({oid})")

        # raw_json 改写：3 条 relation 的安家端→安氏 + entities 补安氏条目（防重放复活）
        for ch in (415, 497):
            row = conn.execute("SELECT raw_json FROM extractions WHERE chapter=?", (ch,)).fetchone()
            if not row:
                continue
            data = json.loads(row["raw_json"])
            changed = False
            for rel in data.get("relations", []):
                if rel.get("type") == "关系" and "安家" in (rel.get("from_name"), rel.get("to_name")) \
                        and (rel.get("attrs", {}).get("关系") in ("夫妻", "叔嫂", "父女")):
                    if rel["from_name"] == "安家":
                        rel["from_name"] = "安氏"
                    else:
                        rel["to_name"] = "安氏"
                    changed = True
            if changed and not any(e.get("name") == "安氏" for e in data.get("entities", [])):
                data["entities"].append({
                    "type": "人物", "name": "安氏", "aliases": [], "classifications": {},
                    "attrs": {"所属势力": "安家", "简介": "安鹧言之女，李曦明之妻"},
                    "evidence": "这是安鹧言之女，也是李曦明的新妻，算是他的嫂子"})
            if changed:
                conn.execute("UPDATE extractions SET raw_json=? WHERE chapter=?",
                             (json.dumps(data, ensure_ascii=False), ch))
                print(f"  raw_json ch{ch} 已改写")
        if dry:
            conn.rollback()
            print("dry-run，不落库")
        else:
            conn.commit()
            print("落库完成")
    except Exception:
        conn.rollback()
        raise


if __name__ == "__main__":
    main()

"""2026-08-26 一次性修正：山越王族氏族"木鹿氏"（势力）被吞进人物"木芽鹿"。

"木芽鹿"（木焦蛮之妹、李玄宣之妾、李渊蛟生母）的别名"木鹿氏"把同名氏族
（山越王族/木鹿镇统治部族，唦摩里所属，ch130-186 共 8 处势力抽取）全吞进人物，
致 3 条氏族语义边错挂人物：
- 唦摩里 --所属--> 木芽鹿 (ch167"木鹿氏的血统算得上不错了") → 迁给木鹿氏
- 李家 --势力关系{扶持}--> 木芽鹿 (ch167"扶持上位…控制东山越") → 迁给木鹿氏
- 木芽鹿 --势力关系{为首}--> 六大氏 (ch185"六大氏以木鹿氏为首") → 端点换向迁给木鹿氏

修法：建势力实体"木鹿氏"，3 边迁端点，木芽鹿剔"木鹿氏"别名（merge_alias_fragments
ALIAS_DROP 已加），raw_json ch236"李渊蛟之母"语境的人物条目改名"木芽鹿"（防重放
建出孤立人物）；ch130-186 的势力条目剔别名后重放将归并到新实体。

用法：
    .venv/bin/python scripts/fix_mulushi.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    return f"rel_{hashlib.md5(f'{from_id}|{to_id}|{type_}'.encode()).hexdigest()[:12]}"


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    def eid(name):
        row = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
        return row["id"] if row else None

    muyalu, shamoli, lijia, liudashi = (eid("木芽鹿"), eid("唦摩里"), eid("李家"), eid("六大氏"))
    assert muyalu and shamoli and lijia and liudashi, "依赖实体缺失"

    try:
        mulu = eid("木鹿氏")
        if not mulu:
            mulu = "势力_" + hashlib.md5("势力|木鹿氏".encode()).hexdigest()[:8]
            conn.execute(
                "INSERT INTO entities(id, type, name, attrs_json, first_chapter, confidence)"
                " VALUES(?,?,?,?,?,?)",
                (mulu, "势力", "木鹿氏",
                 json.dumps({"层级": "氏族（山越王族）", "立场": "归附李家", "首领": "唦摩里",
                             "简介": "山越王族氏族、木鹿镇统治部族，唦摩里为新王；木焦蛮、"
                                     "木芽鹿兄妹出身此族；东山越六大氏之首"}, ensure_ascii=False),
                 130, 0.9))
            print(f"建实体 木鹿氏 {mulu}")
        else:
            print(f"木鹿氏已存在 {mulu}")

        # (定位, 迁移)：swap=True 表示 from/to 互换后再换端点（木芽鹿→木鹿氏 为首边）
        plan = [
            ((shamoli, muyalu, "所属", 167), (shamoli, mulu), False),
            ((lijia, muyalu, "势力关系", 167), (lijia, mulu), False),
            ((muyalu, liudashi, "势力关系", 185), (mulu, liudashi), True),
        ]
        for (of, ot, typ, och), (nf, nt), _ in plan:
            rows = conn.execute(
                "SELECT id, attrs_json FROM relations WHERE from_id=? AND to_id=? AND type=?"
                " AND chapter=?", (of, ot, typ, och)).fetchall()
            nid = rel_id(nf, nt, typ)
            for r in rows:
                if conn.execute("SELECT 1 FROM relations WHERE id=?", (nid,)).fetchone():
                    print(f"  跳过迁移边 {nid}（已存在）")
                else:
                    conn.execute(
                        "UPDATE relations SET id=?, from_id=?, to_id=? WHERE id=?",
                        (nid, nf, nt, r["id"]))
                    conn.execute(
                        "UPDATE relation_events SET rid=?, from_id=?, to_id=? WHERE rid=?",
                        (nid, nf, nt, r["id"]))
                    print(f"  迁边 {r['id']} -> {nid}（端点换为木鹿氏）")

        # raw_json：ch236 "木鹿氏"人物条目（李渊蛟之母语境）改名木芽鹿
        row = conn.execute("SELECT raw_json FROM extractions WHERE chapter=236").fetchone()
        if row:
            data = json.loads(row["raw_json"])
            for e in data.get("entities", []):
                if e.get("name") == "木鹿氏" and e.get("type") == "人物":
                    e["name"] = "木芽鹿"
                    print("  raw_json ch236 人物条目 木鹿氏→木芽鹿")
            for rel in data.get("relations", []):
                if rel.get("type") == "关系" and "木鹿氏" in (rel.get("from_name"), rel.get("to_name")):
                    if rel["from_name"] == "木鹿氏":
                        rel["from_name"] = "木芽鹿"
                    else:
                        rel["to_name"] = "木芽鹿"
            conn.execute("UPDATE extractions SET raw_json=? WHERE chapter=236",
                         (json.dumps(data, ensure_ascii=False),))
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

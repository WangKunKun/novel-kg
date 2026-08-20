"""2026-08-20 一次性存量修正：仙基类四拆（功法/术法/仙基轮/道具）+ 修炼关系拆分。

用法：
    .venv/bin/python scripts/fix_xianji.py data/novel.db           # 真跑
    .venv/bin/python scripts/fix_xianji.py data/novel.db --dry-run # 只打印
"""
import hashlib
import sqlite3
import sys

# 33 个原"仙基"实体的人工归类（按 2026-08-19 调查 + 2026-08-20 确认）
NAME_TO_TYPE = {
    # 功法：诀/经/秘旨结尾 + 养轮法/接引法（"法"结尾但语义是修炼方法体系）
    "七月练气真诀": "功法", "元清御雨诀": "功法", "天元练气诀": "功法",
    "太阴吐纳养轮经": "功法", "太阴吐纳练气诀": "功法", "月华纪要秘旨": "功法",
    "月湖映秋诀": "功法", "玄水剑诀": "功法", "金光诀": "功法",
    "养轮法": "功法", "青元养轮法": "功法", "接引法": "功法",
    # 术法：术结尾 + 避水法/灵中符法/祭萃夺元法（施放型） + 月阙剑弧（剑术招式）
    "净衣术": "术法", "灵雨术": "术法", "玄珠祀灵术": "术法", "金光术": "术法",
    "驱邪术": "术法", "避水法": "术法", "灵中符法": "术法", "祭萃夺元法": "术法",
    "月阙剑弧": "术法",
    # 仙基：轮（筑基根基本体）
    "青元轮": "仙基", "周行轮": "仙基", "承明轮": "仙基",
    "玄景轮": "仙基", "玉京轮": "仙基", "胎息青元轮": "仙基",
    # 道具：气/月华/玄光类突破资源 + 玄珠符种（物品）
    "夜月凛气": "道具", "焰中乌气": "道具", "小清灵气": "道具",
    "太阴月华": "道具", "太阴玄光": "道具", "玄珠符种": "道具",
}

# 旧"修炼"关系按 to 端新类型映射到新关系名
REL_BY_TO_TYPE = {"功法": "修炼", "仙基": "修成", "术法": "施展", "道具": "持有"}


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    """与 resolve._rel_id 完全一致，保证续跑时 (from,to,type) 幂等。"""
    key = f"{from_id}|{to_id}|{type_}"
    return f"rel_{hashlib.md5(key.encode()).hexdigest()[:12]}"


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    xianji = conn.execute(
        "SELECT id, name FROM entities WHERE type='仙基'"
    ).fetchall()
    print(f"仙基实体 {len(xianji)} 个，映射表覆盖 {len(NAME_TO_TYPE)} 个")
    id_to_newtype = {}
    for row in xianji:
        new_type = NAME_TO_TYPE.get(row["name"])
        if new_type is None:
            print(f"  !! 未映射，跳过: {row['name']}")
            continue
        id_to_newtype[row["id"]] = new_type
        mark = "（保持仙基）" if new_type == "仙基" else f" -> {new_type}"
        print(f"  {row['name']}{mark}")

    # 关系修正：旧"修炼"按 to 端实体的新类型映射到新关系名，再重算确定性 id
    rels = conn.execute("SELECT * FROM relations WHERE type='修炼'").fetchall()
    rel_changes: list[tuple[str, str, str]] = []  # (旧id, 新id, 新关系名)
    for r in rels:
        to_entity_type = id_to_newtype.get(r["to_id"], "功法")  # to 端不在映射内的默认功法
        new_rel_type = REL_BY_TO_TYPE[to_entity_type]
        new_id = rel_id(r["from_id"], r["to_id"], new_rel_type)
        if new_id != r["id"] or new_rel_type != "修炼":
            rel_changes.append((r["id"], new_id, new_rel_type))
    print(f"修炼关系 {len(rels)} 条，需改名/改 id {len(rel_changes)} 条")

    if dry:
        print("dry-run，不落库")
        return

    with conn:
        for eid, new_type in id_to_newtype.items():
            conn.execute("UPDATE entities SET type=? WHERE id=?", (new_type, eid))
        for old_id, new_id, new_type in rel_changes:
            hit = conn.execute(
                "SELECT 1 FROM relations WHERE id=?", (new_id,)
            ).fetchone()
            if hit:  # 目标 id 已存在（同边早以新类型入库过），旧行作废
                conn.execute("DELETE FROM relations WHERE id=?", (old_id,))
            else:
                conn.execute(
                    "UPDATE relations SET id=?, type=? WHERE id=?",
                    (new_id, new_type, old_id),
                )
        # 4) 同步修 extractions.raw_json：否则 pipeline 重放 1-70 章时按旧"仙基"
        #    type 会重建重复实体，污染本次修正。
        import json

        for row in conn.execute("SELECT chapter, raw_json FROM extractions").fetchall():
            data = json.loads(row["raw_json"])
            dirty = False
            for e in data.get("entities", []):
                if e.get("type") == "仙基":
                    e["type"] = NAME_TO_TYPE.get(e.get("name"), "仙基")
                    dirty = True
            for r in data.get("relations", []):
                if r.get("type") == "修炼":
                    to_name = r.get("to_name", "")
                    to_type = NAME_TO_TYPE.get(to_name, "仙基" if to_name.endswith("轮") else "功法")
                    r["type"] = REL_BY_TO_TYPE[to_type]
                    dirty = True
            if dirty:
                conn.execute(
                    "UPDATE extractions SET raw_json=? WHERE chapter=?",
                    (json.dumps(data, ensure_ascii=False), row["chapter"]),
                )
    print("落库完成")

    for row in conn.execute(
        "SELECT type, COUNT(*) n FROM entities GROUP BY type ORDER BY n DESC"
    ):
        print(f"  {row['type']}: {row['n']}")
    for row in conn.execute(
        "SELECT type, COUNT(*) n FROM relations GROUP BY type ORDER BY n DESC"
    ):
        print(f"  关系 {row['type']}: {row['n']}")


if __name__ == "__main__":
    main()

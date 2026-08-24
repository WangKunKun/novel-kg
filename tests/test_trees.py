"""trees.py 单测：内存 sqlite fixture，人物 p_{name}/关系 r_* 命名见 helper。"""
import json
import sqlite3

import pytest


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
    CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, canonical_id TEXT,
        attrs_json TEXT, first_chapter INTEGER, confidence REAL, status TEXT);
    CREATE TABLE relations (id TEXT PRIMARY KEY, from_id TEXT, to_id TEXT, type TEXT,
        attrs_json TEXT, chapter INTEGER, evidence TEXT);
    """
    )
    return conn


def add_person(conn, name, jingjie="", jianjie="", chapter=1, type_="人物"):
    conn.execute(
        "INSERT INTO entities VALUES (?,?,?,?,?,?,?,?)",
        (f"p_{name}", type_, name, f"p_{name}",
         json.dumps({"境界": jingjie, "简介": jianjie}, ensure_ascii=False),
         chapter, 1.0, "confirmed"),
    )


def add_rel(conn, a, b, kind, chapter=1, key="关系", type_="关系"):
    conn.execute(
        "INSERT INTO relations VALUES (?,?,?,?,?,?,?)",
        (f"r_{a}_{b}_{kind}", f"p_{a}", f"p_{b}", type_,
         json.dumps({key: kind}, ensure_ascii=False), chapter, ""),
    )
# 注意：relations 表 7 列（无 confidence），与 data/novel.db 实际 schema 一致


@pytest.fixture
def fam_db():
    """三代家族 + 旁支 + 配偶 + 无连通同姓外人。"""
    conn = make_db()
    add_person(conn, "李木田", jingjie="筑基", chapter=2)
    add_person(conn, "李根水", chapter=2)
    add_person(conn, "李长湖", jingjie="胎息三层", jianjie="李木田之子", chapter=3)
    add_person(conn, "李通崖", jingjie="紫府", chapter=3)
    add_person(conn, "田芸", chapter=3)
    add_person(conn, "李玄宣", chapter=23)
    add_person(conn, "任氏", jianjie="李长湖之妻", chapter=5)
    add_person(conn, "李玄锋", chapter=49)
    add_person(conn, "李妃若", chapter=190)  # 同姓外人：无亲属边
    # 方向已修正（from=长辈）
    add_rel(conn, "李木田", "李长湖", "父子")
    add_rel(conn, "李木田", "李通崖", "父子")
    add_rel(conn, "李长湖", "李玄宣", "父子")
    add_rel(conn, "任氏", "李玄宣", "母子")
    add_rel(conn, "李长湖", "任氏", "夫妻")
    add_rel(conn, "李通崖", "李玄锋", "父子")
    add_rel(conn, "李通崖", "田芸", "夫妻")
    add_rel(conn, "李木田", "李根水", "兄弟")
    return conn


def test_li_family_members_includes_spouse_excludes_stranger(fam_db):
    from novel_kg.trees import li_family_members

    members = li_family_members(fam_db)
    names = {fam_db.execute("SELECT name FROM entities WHERE id=?", (i,)).fetchone()["name"]
             for i in members}
    assert names == {"李木田", "李根水", "李长湖", "李通崖", "田芸", "任氏",
                     "李玄宣", "李玄锋"}
    assert "李妃若" not in names

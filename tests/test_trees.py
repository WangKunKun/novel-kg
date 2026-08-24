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


def test_edge_kind_key_fallback_and_paren_strip():
    from novel_kg.trees import edge_kind
    import json as _j
    assert edge_kind(_j.dumps({"关系": "父子"}, ensure_ascii=False)) == "父子"
    assert edge_kind(_j.dumps({"性质": "父子"}, ensure_ascii=False)) == "父子"  # 键回退
    assert edge_kind(_j.dumps({"关系": "敌对（击杀）"}, ensure_ascii=False)) == "敌对"  # 去括号
    assert edge_kind(None) == ""
    assert edge_kind("not-json{") == ""


def test_person_dead_and_sect_from_load(fam_db):
    from novel_kg.trees import DEAD_KEYWORDS, _load_persons
    # 殁者：简介含死亡关键词
    from tests.test_trees import add_person
    add_person(fam_db, "亡者甲", jianjie="战死于南疆", chapter=10)
    # sect：所属边排除血脉家族（李家），取第一个宗门
    from tests.test_trees import add_rel
    add_person(fam_db, "青池宗", type_="势力")
    add_person(fam_db, "李家", type_="势力")
    add_rel(fam_db, "李通崖", "李家", "所属", type_="所属", chapter=4)
    add_rel(fam_db, "李通崖", "青池宗", "所属", type_="所属", chapter=5)
    persons = _load_persons(fam_db)
    assert persons["p_亡者甲"].dead is True
    assert persons["p_李木田"].dead is False
    assert persons["p_李通崖"].sect == "青池宗"
    assert persons["p_李长湖"].sect == ""  # 无所属边


def test_build_family_tree_generations(fam_db):
    from novel_kg.trees import build_family_tree, li_family_members

    tree = build_family_tree(fam_db, li_family_members(fam_db))
    g = {tree.persons[pid].name: tree.persons[pid].generation
         for pid in tree.persons}
    assert g["李木田"] == 0 and g["李根水"] == 0
    assert g["李长湖"] == 1 and g["李通崖"] == 1
    assert g["李玄宣"] == 2 and g["李玄锋"] == 2
    # 嫁入配偶靠夫妻边同层
    assert g["任氏"] == 1 and g["田芸"] == 1
    # 亲子边进树，兄弟边不进（共同父隐含）
    kinds = {(k, tree.persons[a].name, tree.persons[b].name) for k, a, b in tree.edges}
    assert ("父子", "李木田", "李通崖") in kinds
    assert all(k != "兄弟" for k, _, _ in kinds)
    assert not tree.issues


def test_build_family_tree_cycle_broken_and_reported(fam_db):
    from novel_kg.trees import build_family_tree, li_family_members

    # 构造环：李玄锋→李木田 错误父边（木田→通崖→玄锋→木田）
    add_rel(fam_db, "李玄锋", "李木田", "父子")
    tree = build_family_tree(fam_db, li_family_members(fam_db))
    assert any("环" in i for i in tree.issues)
    # 破边规则：去掉指向环内首现最早子端（最可能的真实始祖）的亲子边
    # → 玄锋→木田 被去掉，木田成为根
    g = {p.name: p.generation for p in tree.persons.values()}
    assert g["李木田"] == 0 and g["李通崖"] == 1 and g["李玄锋"] == 2


def test_build_family_tree_orphan_adoption(fam_db):
    from novel_kg.trees import build_family_tree, li_family_members

    # 孤儿：仅祖孙边连接（+2 代）；旁支仅叔侄边（+1 代）
    add_person(fam_db, "李孤孙", chapter=60)
    add_person(fam_db, "李旁侄", chapter=61)
    add_rel(fam_db, "李木田", "李孤孙", "祖孙")
    add_rel(fam_db, "李木田", "李旁侄", "族叔侄")
    tree = build_family_tree(fam_db, li_family_members(fam_db))
    g = {p.name: p.generation for p in tree.persons.values()}
    assert g["李孤孙"] == 2   # 祖孙 +2
    assert g["李旁侄"] == 1   # 族叔侄 +1


def test_build_family_tree_multi_parent_reported(fam_db):
    from novel_kg.trees import build_family_tree, li_family_members

    # 给李玄宣再添一个错误父边 → 多父报告且不崩溃
    add_person(fam_db, "李坏数据", chapter=2)
    add_rel(fam_db, "李坏数据", "李玄宣", "父子")
    tree = build_family_tree(fam_db, li_family_members(fam_db))
    assert any("多父" in i or "多母" in i for i in tree.issues)
    assert tree.persons["p_李玄宣"].generation == 2


@pytest.fixture
def master_db(fam_db):
    """青池宗：司元白、李尺泾(多重所属)、郁慕仙 为成员；唐元乌、叶秋阳 为外人。"""
    for name in ("司元白", "唐元乌", "叶秋阳", "郁慕仙"):
        add_person(fam_db, name, chapter=100)
    add_person(fam_db, "李尺泾", jingjie="筑基", chapter=3)
    add_rel(fam_db, "司元白", "李尺泾", "师徒", chapter=100)     # 司→李，双成员
    add_rel(fam_db, "唐元乌", "郁慕仙", "师徒", chapter=120)     # 唐为外节点
    add_rel(fam_db, "李项平", "叶秋阳", "师徒", chapter=50)      # 双方都不是成员：不进树
    add_rel(fam_db, "司元白", "李尺泾", "师兄弟", chapter=99)    # 同门边
    for m in ("司元白", "李尺泾", "郁慕仙"):
        add_rel(fam_db, m, "青池宗", "所属", type_="所属")
    add_rel(fam_db, "李尺泾", "李家", "所属", type_="所属")      # 多重所属
    add_person(fam_db, "青池宗", type_="势力")
    return fam_db


def test_build_master_tree(master_db):
    from novel_kg.trees import build_master_tree

    tree = build_master_tree(master_db, "青池宗")
    names = {p.name for p in tree.persons.values()}
    # 成员 + 外节点唐元乌；叶秋阳/李项平（非成员边）不进
    assert names == {"司元白", "李尺泾", "郁慕仙", "唐元乌"}
    assert tree.persons["p_唐元乌"].foreign is True
    assert tree.persons["p_司元白"].foreign is False
    # 师承分层：师0徒1
    assert tree.persons["p_司元白"].generation == 0
    assert tree.persons["p_李尺泾"].generation == 1
    # 李尺泾多重所属：sect 标注青池宗（排除李家）
    assert tree.persons["p_李尺泾"].sect == "青池宗"


def test_render_master_tree_foreign_style(master_db):
    from novel_kg.trees import build_master_tree, render_dot, render_mermaid

    tree = build_master_tree(master_db, "青池宗")
    dot = render_dot(tree)
    assert '[label="师徒", style=dashed]' in dot          # 外节点师徒边虚线
    assert 'style="rounded,dashed"' in dot                 # 外节点框虚线
    assert "同门" in dot                                   # 师兄弟边标签
    mm = render_mermaid(tree)
    assert "-->|师徒|" in mm and "---|同门|" in mm
    assert ":::foreign" in mm                             # 外节点样式（mermaid 节点级）


def test_master_tree_dangling_apprentice_tolerated(fam_db):
    from novel_kg.trees import build_master_tree

    add_person(fam_db, "甲师父", chapter=100)
    add_rel(fam_db, "甲师父", "青池宗", "所属", type_="所属")
    add_person(fam_db, "青池宗", type_="势力")
    add_rel(fam_db, "甲师父", "幽灵", "师徒", chapter=100)  # 幽灵悬空
    tree = build_master_tree(fam_db, "青池宗")
    assert {p.name for p in tree.persons.values()} == {"甲师父"}
    assert any("悬空" in i for i in tree.issues)
    # 渲染不崩溃
    from novel_kg.trees import render_dot, render_mermaid
    assert "甲师父" in render_dot(tree)
    assert "甲师父" in render_mermaid(tree)


def test_export_family_tree_files(tmp_path, fam_db):
    """对文件库导出族谱三件套；dot 缺失时至少有 .md（运行时判断，不断言 dot 存在）。"""
    import shutil
    import sys
    sys.path.insert(0, "scripts")
    import sqlite3 as _s
    import export_tree

    db_path = tmp_path / "t.db"
    fdb = _s.connect(db_path)
    fdb.executescript(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, canonical_id TEXT,"
        "attrs_json TEXT, first_chapter INTEGER, confidence REAL, status TEXT);"
        "CREATE TABLE relations (id TEXT PRIMARY KEY, from_id TEXT, to_id TEXT, type TEXT,"
        "attrs_json TEXT, chapter INTEGER, evidence TEXT);")
    for row in fam_db.execute("SELECT * FROM entities"):
        fdb.execute("INSERT INTO entities VALUES (?,?,?,?,?,?,?,?)", tuple(row))
    for row in fam_db.execute("SELECT * FROM relations"):
        fdb.execute("INSERT INTO relations VALUES (?,?,?,?,?,?,?)", tuple(row))
    fdb.commit()

    out = tmp_path / "exports"
    export_tree.run(["族谱", "--db", str(db_path), "--out", str(out)])
    md = (out / "李氏族谱.md").read_text(encoding="utf-8")
    assert "graph TD" in md and "李木田" in md
    if shutil.which("dot"):
        assert (out / "李氏族谱.svg").exists()
        assert (out / "李氏族谱.png").exists()


def test_render_dot_and_mermaid(fam_db):
    from novel_kg.trees import build_family_tree, li_family_members, render_dot, render_mermaid

    tree = build_family_tree(fam_db, li_family_members(fam_db))
    dot = render_dot(tree)
    assert dot.startswith("digraph")
    assert 'rankdir=TB' in dot
    assert "李通崖\\n[紫府]" in dot          # 名字+境界（dot label 用 \n 换行）
    assert "李木田" in dot and "任氏" in dot
    assert "{rank=same" in dot               # 夫妻同层
    mm = render_mermaid(tree)
    assert mm.startswith("graph TD")
    assert "-->" in mm and "---" in mm       # 亲子箭头 + 夫妻连线
    assert "李玄宣" in mm and "李木田" in mm


def test_render_dot_style_quoted_valid_syntax(master_db):
    """style 属性值必须带引号（含逗号的 rounded,dashed 否则是非法 dot）。"""
    import subprocess
    from novel_kg.trees import build_master_tree, render_dot

    tree = build_master_tree(master_db, "青池宗")
    dot = render_dot(tree)
    assert 'style="rounded,dashed"' in dot
    # 喂给真实 dot 验证语法（环境无 dot 时跳过）
    import shutil
    if shutil.which("dot"):
        subprocess.run(["dot", "-Tsvg"], input=dot.encode("utf-8"),
                       capture_output=True, check=True)

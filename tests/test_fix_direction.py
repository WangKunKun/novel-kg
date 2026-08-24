# tests/test_fix_direction.py
"""方向修正单测：简介判向 / 幂等 / 重复边合并 / 无法判定进清单。"""
import sys

from tests.test_trees import add_person, add_rel, make_db


def _setup():
    conn = make_db()
    add_person(conn, "甲父", jianjie="甲之父", chapter=1)
    add_person(conn, "甲", jianjie="甲父之子", chapter=2)
    add_person(conn, "乙", jianjie="乙是丙的师父", chapter=3)
    add_person(conn, "丙", jianjie="", chapter=4)
    add_person(conn, "丁", jianjie="", chapter=5)
    add_person(conn, "戊", jianjie="", chapter=6)
    # 方向错：子→父（应为 父→子）
    add_rel(conn, "甲", "甲父", "父子")
    # 方向错：徒→师（应为 师→徒）
    add_rel(conn, "丙", "乙", "师徒")
    # 无法判定：丁戊 兄弟（对称类，不动）+ 一条无信号父子
    add_rel(conn, "丁", "戊", "兄弟")
    add_rel(conn, "丁", "戊", "父子", chapter=2)  # 无简介信号 → 清单
    return conn


def test_fix_direction_swaps_and_reports():
    sys.path.insert(0, "scripts")
    from fix_relation_direction import plan_fixes

    conn = _setup()
    swap, review = plan_fixes(conn)
    # 甲-甲父：甲简介"甲父之子"→甲父是长辈→应交换
    assert any(a == "p_甲" and b == "p_甲父" for a, b in swap)
    # 丙-乙师徒：乙简介"丙的师父"→乙是师→应交换
    assert any(a == "p_丙" and b == "p_乙" for a, b in swap)
    # 丁戊父子无信号 → review
    assert any(a == "p_丁" and b == "p_戊" for a, b in review)


def test_apply_and_idempotent(tmp_path):
    sys.path.insert(0, "scripts")
    from fix_relation_direction import apply_fixes, plan_fixes

    conn = _setup()
    swap, review = plan_fixes(conn)
    apply_fixes(conn, swap)
    # 再规划：无新交换（幂等）
    swap2, _ = plan_fixes(conn)
    assert not any(a == "p_甲" and b == "p_甲父" for a, b in swap2)
    # 落库方向验证：甲父→甲
    row = conn.execute(
        "SELECT e1.name, e2.name FROM relations r JOIN entities e1 ON r.from_id=e1.id "
        "JOIN entities e2 ON r.to_id=e2.id WHERE r.attrs_json LIKE '%父子%' "
        "AND e1.name='甲父'").fetchone()
    assert row is not None and row[1] == "甲"


def test_merge_opposite_duplicate_edges():
    sys.path.insert(0, "scripts")
    from fix_relation_direction import apply_fixes, plan_fixes

    conn = _setup()
    # 加一条方向相反的重复边：甲父→甲 父子（与 甲→甲父 并存）
    add_rel(conn, "甲父", "甲", "父子", chapter=3)
    swap, _ = plan_fixes(conn)
    apply_fixes(conn, swap)
    n = conn.execute(
        "SELECT COUNT(*) FROM relations r JOIN entities e1 ON r.from_id=e1.id "
        "JOIN entities e2 ON r.to_id=e2.id WHERE r.attrs_json LIKE '%父子%' "
        "AND e1.name='甲父' AND e2.name='甲'").fetchone()[0]
    assert n == 1  # 合并为一条


def test_events_repointed_on_swap_and_merge():
    sys.path.insert(0, "scripts")
    from fix_relation_direction import apply_fixes, plan_fixes

    conn = _setup()
    # 甲→甲父 swap 目标边 + 各挂一条事件
    conn.execute(
        "INSERT INTO relation_events(rid, from_id, to_id, type, attrs_json, chapter, evidence) "
        "VALUES ('r_甲_甲父_父子','p_甲','p_甲父','关系','{\"关系\": \"父子\"}',2,'')")
    # 反向重复边 + 事件
    add_rel(conn, "甲父", "甲", "父子", chapter=3)
    conn.execute(
        "INSERT INTO relation_events(rid, from_id, to_id, type, attrs_json, chapter, evidence) "
        "VALUES ('r_甲父_甲_父子','p_甲父','p_甲','关系','{\"关系\": \"父子\"}',3,'')")
    swap, _ = plan_fixes(conn)
    apply_fixes(conn, swap)
    rows = conn.execute(
        "SELECT rid, from_id, to_id FROM relation_events WHERE attrs_json LIKE '%父子%'").fetchall()
    # swap 分支：rid 改为 md5 新 id，端点同步为 甲父→甲
    sw = [r for r in rows if r["from_id"] == "p_甲父" and r["to_id"] == "p_甲"]
    assert sw and all(r["rid"].startswith("rel_") for r in sw)
    # 合并分支：原 r_甲父_甲_父子 的事件也改挂新 rid + 端点方向正确
    assert not any(r["rid"] == "r_甲父_甲_父子" for r in rows)
    assert all(r["from_id"] == "p_甲父" for r in rows if r["rid"].startswith("rel_"))
    # 两条事件挂同一条保留边
    kept = {r["rid"] for r in rows}
    assert len(kept) == 1


def test_merge_skipped_on_kind_mismatch():
    sys.path.insert(0, "scripts")
    from fix_relation_direction import apply_fixes, plan_fixes

    conn = _setup()
    # 反向存在同 pair 但不同 kind 的边（祖孙），占住 rel_id(甲父,甲,关系) 的 md5 id
    # ——构造方式：直接把反向父子边改成祖孙 kind
    add_rel(conn, "甲父", "甲", "祖孙", chapter=3)
    # 手工把它的 id 改成 rel_id(p_甲父, p_甲, 关系) 以占位
    import hashlib
    rid = "rel_" + hashlib.md5("p_甲父|p_甲|关系".encode()).hexdigest()[:12]
    conn.execute("UPDATE relations SET id=? WHERE id='r_甲父_甲_祖孙'", (rid,))
    conn.commit()
    swap, _ = plan_fixes(conn)
    assert any(a == "p_甲" and b == "p_甲父" for a, b in swap)
    apply_fixes(conn, swap)
    # 父子边未被删除（方向仍错但保留），祖孙边未被动
    n = conn.execute(
        "SELECT COUNT(*) FROM relations r JOIN entities e1 ON r.from_id=e1.id "
        "JOIN entities e2 ON r.to_id=e2.id WHERE r.attrs_json LIKE '%父子%'").fetchone()[0]
    assert n >= 1  # 甲→甲父 父子还在（未合并未删除）


def test_gen_table_and_spouse_propagation():
    """信号②③：字辈表判向 + 夫妻同辈传递（外姓配偶经字辈对端定向）。"""
    sys.path.insert(0, "scripts")
    from fix_relation_direction import plan_fixes

    conn = make_db()
    add_person(conn, "李木田", chapter=1)
    add_person(conn, "李玄宣", chapter=2)
    add_person(conn, "任氏", jianjie="", chapter=3)   # 外姓，无简介信号
    # 错向：玄→木田 父子（字辈：玄3 > 木1 → 木田为 from → 应交换）
    add_rel(conn, "李玄宣", "李木田", "父子")
    # 夫妻同辈传递：玄宣—任氏 夫妻 + 错向母子 任氏→李木田？
    # 任氏经夫妻边得辈分3，木田辈分1 → 木田为 from → 应交换
    add_rel(conn, "李玄宣", "任氏", "夫妻")
    add_rel(conn, "任氏", "李木田", "母子")
    swap, review = plan_fixes(conn)
    assert any(a == "p_李玄宣" and b == "p_李木田" for a, b in swap)
    assert any(a == "p_任氏" and b == "p_李木田" for a, b in swap)
    assert not review

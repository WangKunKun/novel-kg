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

# scripts/fix_relation_direction.py
"""2026-08-24 一次性修正：统一"关系"边方向 from=长辈/师 → to=晚辈/徒。

信号优先级：① attrs 简介"X之子/之父/之母/之徒/之师"互指文本（最强）
② 李家字辈表（LI_GEN_TABLE，原文硬设定）+ 夫妻/兄弟同辈传递定辈分，辈分小者为 from
③ 仍无信号的长幼/师徒边 → 人工核查清单（docs/reports/relation-direction-review.md）
对称类（夫妻/兄弟/敌对等）不动。交换端点后按 rel_id(from,to,type) 重算 id，
撞 id 即方向相反的重复边 → 合并（删旧边，事件 rid 改挂）。幂等可重跑。

用法：
    .venv/bin/python scripts/fix_relation_direction.py data/novel.db [--dry-run]

人工核查结论（真库执行后在此记录，格式参考 scripts/merge_alias_fragments.py）：
- （待 Task 7 填写）
注：本脚本不防重放复活——从 raw_json 重建库后需重跑。
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from novel_kg.trees import edge_kind  # noqa: E402

# from=长（长辈→晚辈）；对称类不动
ELDER_KINDS = {"父子", "母子", "父女", "母女", "祖孙", "叔侄", "姑侄", "舅甥",
               "族叔侄", "后裔"}
MASTER_KINDS = {"师徒"}

# 简介文本模式：命中即"对方名"是声明中的角色
BIO_ROLE = {
    "之子": "child", "之女": "child", "之父": "parent", "之母": "parent",
    "之徒": "apprentice", "之师": "master", "的师父": "master", "的徒弟": "apprentice",
}


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    """与 resolve._rel_id 一致，保证幂等。"""
    return f"rel_{hashlib.md5(f'{from_id}|{to_id}|{type_}'.encode()).hexdigest()[:12]}"


def _bios(conn) -> dict[str, str]:
    return {r["id"]: _safe_json(r["attrs_json"]).get("简介", "")
            for r in conn.execute("SELECT id, attrs_json FROM entities WHERE type='人物'")}


def _safe_json(raw):
    try:
        return json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _bio_signal(my_bio: str, other_name: str) -> str | None:
    """我方简介提到对方时的角色：返回 child（我是子）/parent/master/apprentice。

    匹配要求 精确的 "对方名+后缀" 连续子串（如 "甲父之子"），名字互为前缀时
    不会误报——"甲"+"之子"="甲之子" 不出现在 "甲父之子" 中，故无需最长优先排序。
    """
    for suffix, role in BIO_ROLE.items():
        if other_name + suffix in my_bio:
            return role
    return None


# 信号③：李家字辈表（男名第二字 → 辈分）。原文锚点：2304"男孩取名唤做李玄锋"（玄=2代子）、
# 10617"你若生了男孩，便从渊，若是女孩，便从清"（渊/清同辈）、10571"李平逸…李谢文的嫡长子，
# 也是李叶生的嫡孙…如今渊字辈还未长开"（平与渊同辈、谢与玄同辈）、22013"李曦峸正是李渊云
# 之子，曦月辈的大哥"（曦/月=渊子辈）。根水与木田同辈（24226"木田老祖之庶弟，根水天祖之幼子"）。
LI_GEN_TABLE = {"木": 1, "根": 1,
                "长": 2, "通": 2, "项": 2, "尺": 2, "叶": 2,
                "玄": 3, "谢": 3,
                "渊": 4, "平": 4, "清": 4,
                "曦": 5, "月": 5}


def _li_gen(name: str) -> int | None:
    """李家三字名（李X?）按第二字查字辈表；带"之父/之母/之子/的师父"后缀的不查。"""
    if len(name) != 3 or not name.startswith("李"):
        return None
    if name[2] in ("父", "母", "子", "师"):
        return None
    return LI_GEN_TABLE.get(name[1])


def _gen_closure(names: dict[str, str], kin: list[tuple[str, str, str]]) -> dict[str, int]:
    """信号②同辈传递：字辈表直接定辈分，夫妻/兄弟边两端同辈迭代扩散。"""
    gen = {pid: g for pid, g in ((pid, _li_gen(n)) for pid, n in names.items()) if g}
    changed = True
    rounds = 0
    while changed and rounds < 10:
        changed, rounds = False, rounds + 1
        for k, a, b in kin:
            if k in ("夫妻", "兄弟", "兄妹", "姐弟", "族兄弟"):
                if a in gen and b not in gen:
                    gen[b] = gen[a]
                    changed = True
                elif b in gen and a not in gen:
                    gen[a] = gen[b]
                    changed = True
    return gen


def plan_fixes(conn) -> tuple[list, list]:
    """返回 (需交换的 (from_id,to_id) 列表, 需人工核查的列表)。

    信号优先级：① 简介"X之子/之父"互指 → ② 字辈表/同辈传递定辈分（辈分小者为 from）。
    """
    bios = _bios(conn)
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, name FROM entities WHERE type='人物'")}
    kin = [(edge_kind(r["attrs_json"]), r["from_id"], r["to_id"])
           for r in conn.execute(
               "SELECT from_id, to_id, attrs_json FROM relations WHERE type='关系'"
           ).fetchall()]
    gens = _gen_closure(names, kin)
    swap, review = [], []
    for kind, a, b in kin:
        if kind not in ELDER_KINDS and kind not in MASTER_KINDS:
            continue
        ra = _bio_signal(bios.get(a, ""), names.get(b, ""))
        rb = _bio_signal(bios.get(b, ""), names.get(a, ""))
        # 分别从 ra/rb 推出 "a 为 from"，两侧同时有信号且矛盾 → 人工核查
        cand_a = {"child": False, "parent": True,
                  "apprentice": False, "master": True}.get(ra)
        cand_b = {"parent": False, "child": True,
                  "master": False, "apprentice": True}.get(rb)
        if cand_a is not None and cand_b is not None and cand_a != cand_b:
            review.append((a, b))
            continue
        a_is_from = cand_a if cand_a is not None else cand_b
        if a_is_from is None and kind in ELDER_KINDS:
            # 信号②③：两端辈分都可定且不等 → 辈分小者（长辈）为 from
            ga, gb = gens.get(a), gens.get(b)
            if ga is not None and gb is not None and ga != gb:
                a_is_from = ga < gb
        if a_is_from is None:
            review.append((a, b))
        elif a_is_from is False:
            swap.append((a, b))
    return swap, review


def apply_fixes(conn, swap) -> list:
    """交换端点+重算 id；撞 id 的重复边合并（事件 rid 改挂保留边）。

    返回因 kind 不一致跳过合并的 (from_id, to_id) 列表（方向未改，需人工核查）。
    """
    skipped_kinds = []
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, name FROM entities WHERE type='人物'")}
    with conn:
        for a, b in swap:
            rows = conn.execute(
                "SELECT * FROM relations WHERE from_id=? AND to_id=? AND type='关系'",
                (a, b)).fetchall()
            for r in rows:
                new_id = rel_id(b, a, r["type"])
                kind = edge_kind(r["attrs_json"])
                # 目标方向已有的同 kind 边（无论 id 风格）→ 重复边，合并到它
                dup = None
                for cand in conn.execute(
                    "SELECT id, attrs_json FROM relations WHERE from_id=? AND to_id=? "
                    "AND type='关系' AND id<>?", (b, a, r["id"])
                ).fetchall():
                    if edge_kind(cand["attrs_json"]) == kind:
                        dup = cand["id"]
                        break
                # 占住 new_id 的其它边（id 不含 kind，可能是同 pair 不同 kind）
                occupant = conn.execute(
                    "SELECT attrs_json FROM relations WHERE id=? AND id<>?",
                    (new_id, r["id"])).fetchone()
                if occupant is not None:
                    occ_kind = edge_kind(occupant["attrs_json"])
                    if occ_kind not in ELDER_KINDS and occ_kind not in MASTER_KINDS \
                            and occ_kind not in ("夫妻", "兄弟", "兄妹", "姐弟", "族兄弟"):
                        # 弱语义占位（亲属/抚养/依附等）让位强语义：删占位后正常交换
                        print(f"  弱语义让位：删 {names.get(b, b)}→{names.get(a, a)}"
                              f"（{occ_kind}），换为 {kind}")
                        conn.execute("DELETE FROM relations WHERE id=?", (new_id,))
                        occupant = None  # 已让位，走下方正常交换分支
                    else:
                        # 强语义占位（方向已对）：同对每类型只留一条（resolve 不变量），
                        # 删错向待修边，事件并入占位边
                        print(f"  同对双强语义：删错向 {names.get(a, a)}→{names.get(b, b)}"
                              f"（{kind}），保留 {occ_kind}")
                        conn.execute("UPDATE relation_events SET rid=? WHERE rid=?",
                                     (new_id, r["id"]))
                        conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                        continue
                if dup is not None or occupant is not None:
                    # 合并：保留边统一改为规范 new_id（dup 为旧风格 id 时归一）
                    if dup is not None and dup != new_id:
                        conn.execute("UPDATE relation_events SET rid=? WHERE rid=?",
                                     (new_id, dup))
                        conn.execute("UPDATE relations SET id=? WHERE id=?",
                                     (new_id, dup))
                    conn.execute("UPDATE relation_events SET rid=?, from_id=?, to_id=? "
                                 "WHERE rid=?", (new_id, b, a, r["id"]))
                    conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                    print(f"  合并重复边 {r['id']} → {new_id}（方向相反已存在）")
                else:
                    conn.execute(
                        "UPDATE relations SET id=?, from_id=?, to_id=? WHERE id=?",
                        (new_id, b, a, r["id"]))
                    conn.execute("UPDATE relation_events SET rid=?, from_id=?, to_id=? "
                                 "WHERE rid=?", (new_id, b, a, r["id"]))
                    print(f"  交换 {a} -> {b} 为 {b} -> {a}")
    return skipped_kinds


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    swap, review = plan_fixes(conn)
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM entities")}
    print(f"待交换 {len(swap)} 条：")
    for a, b in swap:
        print(f"  {names.get(a, a)} -> {names.get(b, b)}")
    print(f"待人工核查 {len(review)} 条")
    if dry:
        return
    skipped = apply_fixes(conn, swap)
    if skipped:
        print(f"未处理（kind 不一致）{len(skipped)} 条，请人工核查：")
        for a, b in skipped:
            print(f"  {names.get(a, a)} — {names.get(b, b)}")
    if review:
        p = Path("docs/reports/relation-direction-review.md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "# 方向待核查关系边\n\n"
            + "\n".join(f"- {names.get(a, a)} — {names.get(b, b)}" for a, b in review),
            encoding="utf-8")
        print(f"核查清单已写入 {p}")
    print("落库完成")


if __name__ == "__main__":
    main()

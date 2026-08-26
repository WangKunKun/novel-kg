"""2026-08-26 批量清理：377-500 章亲属边反向重抽造成的 75 组双向边 + 语义错边。

成因：新章节抽取把大量既有亲属关系反向又建一遍（如 渊蛟→归鸾/归鸾→渊蛟 各一条夫妻），
双向亲子边构成有向 2-环，族谱分层崩溃（issues 52+ 条未定位级联）。

两步：
1. KIND_DEL 语义错边个案（人工核对原文/批次结论后判定，kind 精确匹配）
2. 双向同 kind 去重：两侧各取最早事件章，删晚的一侧（旧边经批次1-6 修正可信）

用法：
    .venv/bin/python scripts/dedupe_kin_edges.py data/novel.db [--dry-run]
"""
import json
import sqlite3
import sys

sys.path.insert(0, ".")
from novel_kg.trees import KIN_ALL, _kin_edges, _load_persons, edge_kind  # noqa: E402


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    import hashlib
    return f"rel_{hashlib.md5(f'{from_id}|{to_id}|{type_}'.encode()).hexdigest()[:12]}"


# (from名, to名, kind)：人工判定的语义错边（含双向两侧都错的）
KIND_DEL = [
    ("李通崖", "李叶生", "兄弟"),      # 叶生是项平堂弟（代1），通崖（代2）错辈
    ("安鹧言", "李妃若", "夫妻"),      # 妃若是木焦蛮之妃（宗女嫁东山越），非安鹧言妻
    ("李曦明", "窦氏", "夫妻"),        # 窦氏是李玄宣正妻=曦明祖母；曦明之妻为安氏
    ("李清虹", "李玄锋", "兄妹"),      # 玄锋是清虹伯父，叔侄边（玄锋→清虹）已有
    ("李曦峸", "李清虹", "姑侄"),      # 清虹是姑（玄岭女），曦字辈是侄——反向
    ("李曦峻", "李清虹", "姑侄"),      # 同上
    ("李曦明", "李清虹", "姑侄"),      # 同上
    ("李清虹", "李景恬", "姑侄"),      # 景恬才是清虹的姑——反向
    ("李通崖", "李曦峸", "后裔"),      # 曦峸是后裔——反向
    ("李玄宣", "李叶生", "叔侄"),      # 叶生是玄宣堂叔祖——反向
    ("李长湖", "李项平", "兄弟"),      # 项平是父；父子边由下方 ADD 补
    ("李项平", "李长湖", "兄弟"),      # 同上（双向都错）
    ("李曦明", "李曦峻", "兄弟"),      # 堂兄弟，留 族兄弟 边
    ("李曦峻", "李曦明", "兄弟"),      # 同上
    ("李曦峸", "李曦治", "兄弟"),      # 堂兄弟，留 族兄弟 边
    ("李曦治", "李曦峸", "兄弟"),      # 同上
    ("萧初庭", "萧初筹", "兄弟"),      # 堂兄弟，留 族兄弟 边
    ("萧初筹", "萧初庭", "兄弟"),      # 同上
    ("李通崖", "柳柔绚", "夫妻"),      # 柳柔绚(ch23 灵窍少女)非通崖妻；通崖之妻田芸
    ("柳柔绚", "李通崖", "夫妻"),      # 双向都错
    ("李渊修", "田芸", "叔侄"),        # 田芸是通崖妻=渊修伯祖母，错辈且双向
    ("田芸", "李渊修", "叔侄"),        # 同上
    ("李谢文", "李通崖", "族叔侄"),    # 谢文=叶生之子（ch30），与通崖同辈——双向都错
    ("李通崖", "李谢文", "族叔侄"),    # 同上
    ("李渊修", "李谢文", "族叔侄"),    # 谢文是渊修叔祖——反向，留 谢文→渊修 侧
    ("李渊平", "李谢文", "族叔侄"),    # 同上
    ("李木田", "李长湖", "父子"),      # 长湖是项平之子=木田之孙；项平→长湖 父子边已 ADD
    ("李妃若", "李叶生", "父女"),      # 反向父女（叶生→妃若 已有）——族谱分层成环主因
    ("李长湖", "柳林云", "母子"),      # 柳林云是木田之妻=长湖祖母；环：项平→长湖→柳林云→木田→项平
    ("李景恬", "田芸", "母女"),        # 反向母女（田芸→景恬 已有）——2-环
    ("李景恬", "田氏", "母女"),        # 同上（田氏并入田芸前的反向边）
    ("李平逸", "李谢文", "父子"),      # 反向父子（谢文→平逸 下方 ADD 补）
    ("李景恬", "柳柔绚", "母女"),      # 柳柔绚是玄字辈儿媳（玄岭妻），非景恬之女
    ("李项平", "田芸", "夫妻"),        # ch3 田芸"属意项平"未成，实嫁通崖（批次5：景恬=通崖&田芸女）
    ("李清晓", "陈冬河", "父女"),      # 反向父女（陈冬河→清晓 已有）
    ("李渊蛟", "木芽鹿", "母子"),      # 反向母子（木芽鹿→渊蛟 已有）；三点环：玄宣→渊蛟→木芽鹿→玄宣
]

ADD = [  # (from, to, kind, ch, evidence)
    ("李项平", "李长湖", "父子", 14, "ch65 项平将李长湖的遗腹子当成李家下一代家主培养"),
    ("李木田", "李叶生", "叔侄", 2, "叶生是李项平堂弟，木田为其伯父（挂靠边曾丢失，重补）"),
    ("李叶生", "李谢文", "父子", 30, "ch30 李叶生之子…天天跟在李玄宣身后东奔西跑"),
    ("李谢文", "李平逸", "父子", 214, "平逸=谢文嫡长子（批次5 结论 10571 行）"),
]


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    def eid(name):
        row = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
        return row["id"] if row else None

    # kind 匹配口径与 trees.edge_kind 一致：关系/性质双键 + "（…）"后缀截断
    KIND_MATCH = ("(json_extract(attrs_json,'$.关系')=? OR json_extract(attrs_json,'$.性质')=?"
                  " OR json_extract(attrs_json,'$.关系') LIKE ?"
                  " OR json_extract(attrs_json,'$.性质') LIKE ?)")

    try:
        n_del = 0
        for fname, tname, kind in KIND_DEL:
            fa, fb = eid(fname), eid(tname)
            if not fa or not fb:
                continue
            rows = conn.execute(
                f"SELECT id FROM relations WHERE type='关系' AND {KIND_MATCH}"
                " AND from_id=? AND to_id=?",
                (kind, kind, kind + "（%", kind + "（%", fa, fb)).fetchall()
            for r in rows:
                conn.execute("DELETE FROM relation_events WHERE rid=?", (r["id"],))
                conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                n_del += 1

        for fname, tname, kind, ch, ev in ADD:
            fa, fb = eid(fname), eid(tname)
            if not fa or not fb:
                continue
            nid = rel_id(fa, fb, "关系")
            if conn.execute("SELECT 1 FROM relations WHERE id=?", (nid,)).fetchone():
                continue
            attrs = json.dumps({"关系": kind}, ensure_ascii=False)
            conn.execute("INSERT INTO relations(id, from_id, to_id, type, attrs_json, chapter,"
                         " evidence) VALUES(?,?,?,?,?,?,?)", (nid, fa, fb, "关系", attrs, ch, ev))
            conn.execute("INSERT INTO relation_events(rid, from_id, to_id, type, attrs_json,"
                         " chapter, evidence) VALUES(?,?,?,?,?,?,?)",
                         (nid, fa, fb, "关系", attrs, ch, ev))

        # 双向同 kind 去重：chapter 早者留
        persons = _load_persons(conn)
        id2name = {pid: p.name for pid, p in persons.items()}
        n_dedupe = 0
        kin = [(k, a, b) for k, a, b in _kin_edges(conn, KIN_ALL)
               if a in id2name and b in id2name]
        eset = set(kin)
        done = set()
        # 注意 _kin_edges 返回 (kind, from, to)：反向边的元组是 (k, to, from)
        for k, a, b in sorted(eset, key=lambda x: id2name[x[1]]):
            if (k, b, a) not in eset or (k, a, b) in done or (k, b, a) in done:
                continue
            done.add((k, a, b)); done.add((k, b, a))

            def first_ch(x, y):
                r = conn.execute(
                    "SELECT MIN(COALESCE((SELECT MIN(chapter) FROM relation_events e"
                    " WHERE e.rid=r.id), r.chapter)) c FROM relations r"
                    f" WHERE r.type='关系' AND {KIND_MATCH} AND r.from_id=? AND r.to_id=?",
                    (k, k, k + "（%", k + "（%", x, y)).fetchone()
                return r["c"] or 10**9

            ca, cb = first_ch(a, b), first_ch(b, a)
            victim_from, victim_to = (b, a) if ca <= cb else (a, b)  # 晚者为 victim
            rows = conn.execute(
                f"SELECT id FROM relations WHERE type='关系' AND {KIND_MATCH}"
                " AND from_id=? AND to_id=?",
                (k, k, k + "（%", k + "（%", victim_from, victim_to)).fetchall()
            for r in rows:
                conn.execute("DELETE FROM relation_events WHERE rid=?", (r["id"],))
                conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                n_dedupe += 1
        print(f"语义删 {n_del} / 去重删 {n_dedupe} / 补边 {len(ADD)}")
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

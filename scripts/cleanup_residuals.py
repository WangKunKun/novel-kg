"""2026-08-24 残留清理：方向核查清单 75 条的人工核查落库 + 族谱多父矛盾修边。

三组操作（边按 (from名, to名, chapter) 定位，避免同对多边歧义）：
SWAP  交换端点（撞 id 的反向重复边自动合并）
DEL   删边（错误关系/弱语义让位/重复反向）
ADD   补边（遗漏的正确关系）

人工核查结论（2026-08-24，对照原文）：
- 木田/根水是兄弟非父子（24226"木田老祖之庶弟，根水天祖之幼子"），双父子边删、补兄弟边
- 叶秋阳(=李秋阳，别名已挂) 23 章为子端错向；24 章 项平→叶秋阳"师徒"系误抽——1355
  "秋阳也是我李氏子弟…传下法门"传法者是李通崖（145/224 族叔侄边已有，无需另建）
- "爷爷"=李木田泛称、"灵窍子"=泛指非人名（7121"家中也没有灵窍子"）——边删+实体删
- 万萧华自环边（67）删
- 陈三水/陈求水是陈二牛长子/次子（2488/2520），40 章子端错向边删（103/40 对向已有）
- 明慧/妖物 280 章师从的是堇莲摩诃（批次4已知偏差"归并后指向法慧"），285 边换向+
  280 边删；妖物补挂堇莲摩诃
- 李曦治→袁湍(333)与袁湍→李曦治(361/376)双向，留后者（曦治随袁湍修行 349/361）
- 江雁是江伯清之子（338 换向后父子）与师徒(331)并存——父子边保留、师徒边语义存疑留档
- 萧家：229 明言"萧元思为族叔"，48 反向边删；萧衔忧是萧初庭仲父（222），272"先祖"边删
- 费家：费逸和是父（15554"两人的父亲费逸和"），249 反向删；桐玉 316 反向删；桐啸是
  望白嫡孙（219 自述）换向
- 安家：安思危/安思明是安鹧言之子（358/27037）不动；安景明↔安鹧言 167/210 双向矛盾留档
- 李岨称李曦峻八叔（374）、窦邑的姑姑是窦氏（19678）——275 换向
- 唦摩里=山越王（208），公子修/李寄蛮皆其子嗣（208:32"留在李家的几个子嗣"），向已对不动
- 族谱多父矛盾：玄宣=长湖子(1774)、玄锋=通崖&田芸子(2304)、景恬=通崖&田芸女(2304龙凤胎)、
  渊蛟=玄宣次子(34064)、平逸=谢文嫡长子(10571)、清虹=玄岭女(11183)——各删错边
- 叶生/叶盛错置 0 代：其与木田的"侄子与伯父"自由文本 kind 不被挂靠识别——补规范叔侄边
留档待人工：袁湍—司元白(332)师徒方向、汲登齐—当代汲家家主(67)、萧如誉↔萧雍灵(154/163)
矛盾、安景明↔安鹧言(167/210)矛盾、江伯清—江雁师徒语义、李清虹—紫府老祖(374)、郁家世系组
注：本脚本不防重放复活（raw_json 未改），重建库后需重跑 fix+本脚本。

用法：
    .venv/bin/python scripts/cleanup_residuals.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys

SWAP = [  # (from名, to名, chapter)
    ("小泽", "陈二牛", 7),
    ("叶秋阳", "叶承福", 23),
    ("叶秋阳", "李通崖", 145),
    ("李玄锋", "叶秋阳", 114),
    ("萧雍灵", "萧初庭", 71),
    ("费桐啸", "费望白", 219),
    ("李清虹", "叶秋阳", 345),
    ("李曦明", "萧元思", 359),
    ("江雁", "江伯清", 338),
    ("窦邑", "窦氏", 275),
    ("明慧", "堇莲摩诃", 285),
]
DEL = [
    ("李木田", "李根水", 7), ("李根水", "李木田", 82),   # 实为兄弟
    ("李项平", "叶秋阳", 24),                              # 误抽（传法者李通崖）
    ("爷爷", "李玄宣", 38),
    ("万萧华", "万萧华", 67),                              # 自环
    ("陈三水", "陈二牛", 40), ("陈求水", "陈二牛", 40),
    ("萧元思", "司元白", 62),                              # "关系说明"键不可识别，196 已有
    ("萧雍灵", "萧元思", 48),                              # 229 明言萧元思为族叔
    ("田有道", "田仲青", 239),                             # 弱语义让位 334 叔侄
    ("田荣", "田有道", 256),
    ("萧宪", "萧久庆", 279),
    ("明慧", "法慧", 280), ("妖物", "法慧", 280),          # 实师从堇莲摩诃
    ("李曦治", "袁湍", 333),                               # 双向，留 361
    ("灵窍子", "田有道", 365),
    ("费望白", "费逸和", 249), ("费桐玉", "费逸和", 316),
    ("萧初庭", "萧衔忧", 272),                             # 222 仲父更确
    # —— 多父矛盾：删错边 ——
    ("李通崖", "李玄宣", None),                            # 玄宣=长湖子
    ("任氏", "李玄锋", None),                              # 玄锋=田芸子
    ("李项平", "李景恬", None), ("柳柔绚", "李景恬", None),  # 景恬=通崖&田芸女
    ("李玄岭", "李渊蛟", None),                            # 渊蛟=玄宣次子
    ("李玄宣", "李平逸", None),                            # 平逸=谢文子
    ("李通崖", "李清虹", None),                            # 清虹=玄岭女
]
ADD = [
    ("李木田", "李根水", "兄弟", 7, "24226'木田老祖之庶弟，根水天祖之幼子'——兄弟非父子"),
    ("堇莲摩诃", "妖物", "师徒", 280, "280 妖物在师尊座下受教诲（师尊为堇莲摩诃）"),
    ("李木田", "李叶生", "叔侄", 2, "叶生是李项平堂弟，木田为其伯父——补规范边供挂靠"),
    ("李木田", "李叶盛", "叔侄", 2, "叶盛是叶生之兄，同为木田侄辈"),
]
DROP_ENTITIES = ["爷爷", "灵窍子"]  # 泛称，无边后删


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    return f"rel_{hashlib.md5(f'{from_id}|{to_id}|{type_}'.encode()).hexdigest()[:12]}"


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    names = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM entities")}

    def eid(n):
        return names.get(n)

    n_swap = n_del = n_add = 0
    with conn:
        for a, b, ch in SWAP:
            fa, fb = eid(a), eid(b)
            if not fa or not fb:
                print(f"  跳过 SWAP {a}-{b}（实体缺失）")
                continue
            q = "SELECT * FROM relations WHERE from_id=? AND to_id=? AND type='关系'"
            rows = [r for r in conn.execute(q, (fa, fb)).fetchall()
                    if ch is None or r["chapter"] == ch]
            for r in rows:
                new_id = rel_id(fb, fa, r["type"])
                dup = conn.execute("SELECT 1 FROM relations WHERE id=?", (new_id,)).fetchone()
                if dup:
                    conn.execute("UPDATE relation_events SET rid=? WHERE rid=?",
                                 (new_id, r["id"]))
                    conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                    print(f"  合并 {a}→{b} 到已有反向边")
                else:
                    conn.execute("UPDATE relations SET id=?, from_id=?, to_id=? WHERE id=?",
                                 (new_id, fb, fa, r["id"]))
                    conn.execute("UPDATE relation_events SET rid=?, from_id=?, to_id=? "
                                 "WHERE rid=?", (new_id, fb, fa, r["id"]))
                    print(f"  交换 {a}→{b} 为 {b}→{a}")
                n_swap += 1
        for a, b, ch in DEL:
            fa, fb = eid(a), eid(b)
            if not fa or not fb:
                continue
            q = ("SELECT id, chapter FROM relations "
                 "WHERE from_id=? AND to_id=? AND type='关系'")
            rows = [r for r in conn.execute(q, (fa, fb)).fetchall()
                    if ch is None or r["chapter"] == ch]
            for r in rows:
                conn.execute("DELETE FROM relation_events WHERE rid=?", (r["id"],))
                conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                print(f"  删边 {a}→{b}（ch{ch or '任意'}）")
                n_del += 1
        for a, b, kind, ch, ev in ADD:
            fa, fb = eid(a), eid(b)
            if not fa or not fb:
                print(f"  跳过 ADD {a}-{b}（实体缺失）")
                continue
            rid = rel_id(fa, fb, "关系")
            if conn.execute("SELECT 1 FROM relations WHERE id=?", (rid,)).fetchone():
                print(f"  跳过 ADD {a}→{b}（已存在）")
                continue
            attrs = json.dumps({"关系": kind}, ensure_ascii=False)
            conn.execute(
                "INSERT INTO relations(id, from_id, to_id, type, attrs_json, chapter, evidence)"
                " VALUES(?,?,?,?,?,?,?)", (rid, fa, fb, "关系", attrs, ch, ev))
            conn.execute(
                "INSERT INTO relation_events(rid, from_id, to_id, type, attrs_json, chapter,"
                " evidence) VALUES(?,?,?,?,?,?,?)", (rid, fa, fb, "关系", attrs, ch, ev))
            print(f"  补边 {a}→{b} {kind}")
            n_add += 1
        for name in DROP_ENTITIES:
            i = eid(name)
            if not i:
                continue
            n = conn.execute(
                "SELECT COUNT(*) c FROM relations WHERE (from_id=? OR to_id=?) "
                "AND type='关系'", (i, i)).fetchone()["c"]
            if n == 0:
                for t in ("relation_events",):
                    conn.execute(f"DELETE FROM {t} WHERE from_id=? OR to_id=?", (i, i))
                conn.execute("DELETE FROM relations WHERE from_id=? OR to_id=?", (i, i))
                conn.execute("DELETE FROM aliases WHERE entity_id=?", (i,))
                conn.execute("DELETE FROM classifications WHERE entity_id=?", (i,))
                conn.execute("DELETE FROM entities WHERE id=?", (i,))
                print(f"  删实体 {name}（泛称，无边）")
    print(f"落库完成：swap {n_swap} / del {n_del} / add {n_add}")


if __name__ == "__main__":
    main()

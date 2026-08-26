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
    # —— 批次8（377-500 章族谱亲子/亲属方向）——
    ("李渊蛟", "李玄锋", 467),   # 叔侄：渊蛟称"仲父"，规范 叔→侄
    ("李曦峻", "李渊平", 380),   # 叔侄：曦峻称"七叔"（曦明之父），规范 叔→侄；撞 430 父子错边先删
    ("李月湘", "萧归鸾", 492),   # 母女：ch397 月湘唤归鸾"娘"，换向撞 456 已有边合并
    ("李周巍", "李承辽", 490),   # 父子：ch479 承辽抱起周巍"靠在父亲胸膛上"，换向撞 493 合并
    ("李渊平", "李通崖", None),  # 祖孙反向：通崖是渊平叔祖（通崖与长湖兄弟，长湖是玄宣之父）→ 规范 祖→孙
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
    # —— 批次8（377-500 章反向亲子边，正向边均已在库）——
    ("李玄宣", "李长湖", 347),   # ch65"项平将李长湖的遗腹子（玄宣）当下一代家主培养"——长湖→玄宣(347)已有
    ("李渊蛟", "李玄宣", 333),   # ch257"长兄李玄宣之子，唤作李渊蛟"——玄宣→渊蛟(474)已有
    ("李渊平", "李玄宣", 380),   # ch380"父亲李玄宣炼制的符箓"——玄宣→渊平(203)已有
    ("李清虹", "李玄岭", 445),   # ch445"她父亲李玄岭与大父李通崖"——玄岭→清虹(261)已有，此为自由文本反向
    ("李清晓", "李景恬", 486),   # ch486"李景恬与陈冬河之女李清晓"——景恬→清晓(267)已有
    ("李玄锋", "李渊蛟", 496),   # ch177"从叔李玄锋"、ch467"仲父"——叔侄非父子，叔侄边 SWAP 后已有
    ("李曦治", "李渊蛟", 487),   # ch395"父亲李渊蛟信中"——渊蛟→曦治(488)已有
    ("李月湘", "李渊蛟", 487),   # ch377"李渊蛟幼女李月湘"——渊蛟→月湘(495)已有
    ("李曦明", "李渊平", 391),   # ch391"不太敢见父亲李渊平"——渊平→曦明(398)已有
    ("李承淮", "李曦治", 487),   # ch408/412"淮儿"——曦治→承淮(479)已有
    ("李曦治", "萧归鸾", 487),   # ch487"母亲持着书…考教"——归鸾→曦治(275)已有
    ("李景恬", "李项平", 91),    # ch91"对父亲李项平的担忧"主语是项平之子（通崖/长湖），错挂景恬；
                               # 木田→项平(1) 已有
    ("李渊平", "李曦峻", 430),   # ch372"渊平最喜欢与自己这个侄子说话"——叔侄非父子，380 叔侄边 SWAP 后已有
    ("李承辽", "李曦峸", 484),   # "继任者（受其移交权力）"语义错抽，ch422 原文是父子+家主传承；曦峸→承辽(477)已有
    # —— 批次8b（377-500 章亲属挂靠边错向/错辈，多为无 chapter 限定的全方向删除）——
    # 环主因：木田→通崖(父子·应为祖孙) + 项平→通崖(兄弟·应为父子) + 项平→木田(父子·反向) 无向三角
    ("李项平", "李木田", None),  # 反向父子（木田→项平(1) 已有）
    ("李木田", "李通崖", None),  # 木田是祖非父（祖孙边下方 ADD 补）
    ("李项平", "李通崖", None),  # 通崖是项平之子非兄弟（父子边下方 ADD 补）
    ("李项平", "李玄锋", None),  # 玄锋是孙（通崖→玄锋 父子下方 ADD 补）
    ("李项平", "李玄岭", None),  # 叔侄错辈（木田→玄岭 祖孙已有）
    ("李项平", "李玄宣", None),  # 叔侄错辈（木田→玄宣 祖孙已有）
    ("李玄锋", "李通崖", None),  # 通崖是玄锋之父
    ("李通崖", "李玄锋", None),  # 玄锋是通崖之子
    ("李木田", "李尺泾", None),  # 尺泾是通崖之弟=木田之孙（ch13"我等远不如尺泾"同辈证）
    ("李景恬", "李尺泾", None),  # 反向叔侄（尺泾→景恬 叔侄已有）
    ("李渊平", "李清晓", None),  # "姐弟"错辈：清晓是景恬之女=渊平表姑辈（清晓-暮云-渊平 已由母子/舅甥连通）
    # 双向重复边各删一侧（保留连通）
    ("李玄岭", "李景恬", None), ("李玄锋", "李景恬", None), ("李景恬", "李玄宣", None),
    ("李尺泾", "李通崖", None), ("李清晓", "萧宪", None), ("李玄宣", "李玄锋", None),
    ("李玄宣", "李玄岭", None),
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
    # —— 批次8b：家谱主链缺失补边 ——
    ("李项平", "李通崖", "父子", 14, "ch14 项平诸子（长湖/通崖）——ch65 项平将李长湖的遗腹子当成下一代家主培养"),
    ("李通崖", "李玄锋", "父子", 230, "批次5 结论：玄锋=通崖&田芸子(2304) 既有，此边被 377-500 章错向边顶掉后缺失"),
    ("李木田", "李通崖", "祖孙", 14, "通崖是项平之子=木田之孙（挂靠边，同木田→玄锋/玄岭/玄宣/景恬 例）"),
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
        # ADD 补的边也按 (from,to,chapter) 定位，会被上面 DEL 的同条目误删后重补，
        # 循环往复还丢重放追加的 events——DEL 跳过 attrs 关系值等于 ADD kind 的边
        add_kinds: dict[tuple[str, str], set] = {}
        for _a, _b, _k, _c, _e in ADD:
            add_kinds.setdefault((_a, _b), set()).add(_k)
        for a, b, ch in DEL:
            fa, fb = eid(a), eid(b)
            if not fa or not fb:
                continue
            q = ("SELECT id, chapter, attrs_json FROM relations "
                 "WHERE from_id=? AND to_id=? AND type='关系'")
            rows = [r for r in conn.execute(q, (fa, fb)).fetchall()
                    if ch is None or r["chapter"] == ch]
            for r in rows:
                try:
                    kind = json.loads(r["attrs_json"] or "{}").get("关系")
                except (TypeError, ValueError):
                    kind = None
                if kind in add_kinds.get((a, b), ()):
                    print(f"  跳过 DEL {a}→{b}（ADD 补的{kind}边，防删补循环）")
                    continue
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

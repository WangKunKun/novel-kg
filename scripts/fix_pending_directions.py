"""2026-08-25 二次修正：direction-review 残留 8 项的原文核查落库。

操作类型（边按 (from名, to名, chapter) 定位）：
SWAP       交换端点（撞 id 的同 kind 反向重复边自动合并，事件改挂保留边）
DEL        删边（事件改挂保留边或随边删除）
ADD        补边（遗漏的正确关系）
DEL_EVENT  删除误抽事件（保留边不动）
MERGE      实体合并（关系/事件/别名/分类/attrs 迁移后删源实体）

人工核查结论（2026-08-25，对照原文 1-376 章）：
- 袁湍—司元白(332) 师徒：司元白为师。简介互证（袁湍=李尺泾四师姐，司元白收李尺泾为徒）
  + 332"师尊司元白又被关押"→ swap
- 汲登齐—当代汲家家主(67) 祖孙：被万家击杀的当代家主是汲登齐祖父。67 原文"击杀了当代
  汲家家主"+"汲登齐的父亲，汲家的少主受辱"+父亲死后汲登齐"坐上了家主之位"→ swap。
  汲登齐之父(67) from=长辈方向本对，不动（第 8 项结案）
- 萧如誉—萧雍灵：两处证据一致雍灵为族叔（154"「族叔！！」萧如誉朝萧雍灵拱手"、163"与
  族叔萧雍灵一个辈分"）→ 154 边（族叔侄）保留，删 163 反向边
- 安景明—安鹧言：鹧言为父。167"父亲安鹧言…「父亲。」安景明恭恭敬敬地应了一声""你我
  父子"+"大殿在安鹧言当家主那一天建造，到安景明出生那一天完工"；210"安鹧言…生出安景明
  这样的天才"→ 167 边 swap 后撞 210 边（父子）合并
- 江伯清—江雁：师徒为准。331 江雁直呼"师傅"；338"惑我父，杀我母…江伯清已死，江雁心中
  又是悲痛"——控诉对象非江伯清，无父子证据，338"父子"事件系误抽 → 删事件。
  "江雁师尊"(270)即江伯清夺舍前的易容皮囊：270 少年劝"您老或可换上一副皮囊"后老农易容
  农妇；老农痛骂紫府金丹道（331 江伯清"丢了紫府金丹道不修，改修咒术异经"）；"我寻我的
  好道基"（332"确是一具上好的肉身"指江雁）→ 实体合并，270 师徒边并入 331 边
- 李清虹—紫府老祖(374)：挂错实体。374 说话者是李玄宣，"此乃老祖之孙女、曾孙"的老祖=
  李通崖（下文孔玉赞"【月阙剑】李通崖仙姿佚貌"；清虹=玄岭之女=通崖孙女、曦峻=曾孙，
  "这对姑侄"印证）→ 删边，374 事件改挂新补的 通崖→清虹 祖孙边（通崖→曦峻后裔边 323 已有）
- 郁家世系：瓯是贵之兄（250 瓯"萧字辈的大哥"+称贵"老五"）→ 补兄弟边；贵为慕高之父
  （250"郁萧贵与郁慕高父子轻敌"，319 父子边已有方向对）与慕仙之父（245"我是慕仙之父"，
  父子边已有方向对）均不动；玉封是萧字辈族叔（250"「玉封族叔呢！」"，250 边 kind 自注
  "郁玉封为族叔"但方向反）→ swap；瓯自环边（250"夫妻"）实为瓯与亡妻合清（蒋女，无实体）
  误抽 → 删；郁萧瓯 250 洞房回忆（十五岁）与行 17947 老翁（一百二十多岁）同一人，无同名
  两人；"郁公子"别名表已挂"郁慕高"

2026-08-25 补充（377-500 章文本证据，chapters 表已入库，不依赖 LLM 抽取）：
- 475 李清虹"郁家正鼎盛之时，几个兄弟各有其能，郁慕仙天资聪慧，郁慕高手段阴狠，还有一人
  叫作郁慕剑，曾败在大父手中"——慕剑与慕高/慕仙同辈兄弟（138 边已有）；"大父"=通崖，
  旁证 通崖→清虹 祖孙边
- 480 安鹧言一生回顾"得了麒麟儿…被郁慕高、郁萧贵灭族杀子…「景明…还是你看得远…」"
  ——鹧言为父方向修正被新章节印证
- 305"叫你四族叔来"的"四族叔"应指萧字辈排行四（贵排行五"老五"之四哥），与慕字辈无关
  ——贵→慕元(199)/慕仙(245)/慕高(319) 三条父子边无矛盾，均维持
- 慕高↔慕仙双向兄弟边（327 慕公子→慕仙 / 305 慕仙→慕公子）重复 → 删 305 留 327

第二轮（fix_relation_direction --dry-run 重审 53 条 review 池，多数方向本正确无需动，
以下 6 条为确有问题者；叶秋阳→李渊平 348 族叔侄经查原文方向正确不动）：
- 安鹧言→安鹧言叔父(244) swap：244"白发老头正是安鹧言的叔父"
- 田仲青→田有道(334) swap：334"田仲青便晓得伯父还是心疼这个独子（田荣）"→有道为伯父
- 萧归鸾→萧如誉(345) swap：345"叔父萧如誉说不准还在里头"
- 郁成宜→郁公子(375) swap 合并：375"郁慕高的第七子郁成宜"，366 父子边已有
- 叶承福→李木田(8) 删：ch8 双向叔侄边重复，两处证据均"是侄子叶承福"→木田为叔
- 郁公子→郁萧贵(309) 删：309 证据"郁萧贵眯眼看着…郁慕高"无父子语义系误抽，319 父子边已对
注：本脚本不防重放复活（raw_json 未改），重建库后需重跑 fix_relation_direction +
cleanup_residuals + 本脚本。

用法：
    .venv/bin/python scripts/fix_pending_directions.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys

SWAP = [  # (from名, to名, chapter) —— 方向反了，换成 to→from（from=长辈/师）
    ("袁湍", "司元白", 332),
    ("汲登齐", "当代汲家家主", 67),
    ("安景明", "安鹧言", 167),
    ("郁萧瓯", "郁玉封", 250),
    # ---- 第二轮（fix 脚本重审 53 条 review 池中确有问题的边）----
    ("安鹧言", "安鹧言叔父", 244),   # 244"白发老头正是安鹧言的叔父"→叔父为长辈端
    ("田仲青", "田有道", 334),       # 334"田仲青便晓得伯父还是心疼这个独子"→有道为伯父
    ("萧归鸾", "萧如誉", 345),       # 345"叔父萧如誉说不准还在里头"→如誉为叔
    ("郁成宜", "郁公子", 375),       # 375"郁慕高的第七子郁成宜"→公子为父，撞 366 边合并
]
DEL = [  # (from名, to名, chapter) —— 错误边；keep=(from名,to名,chapter) 事件改挂保留边
    ("萧如誉", "萧雍灵", 163, ("萧雍灵", "萧如誉", 154)),
    ("郁萧瓯", "郁萧瓯", 250, None),          # 自环：亡妻合清误抽，无实体可挂
    ("李清虹", "紫府老祖", 374, ("李通崖", "李清虹", 374)),  # keep 为下方 ADD 的新边
    ("郁慕仙", "郁公子", 305, ("郁公子", "郁慕仙", 327)),  # 双向兄弟边去重，留 327
    # ---- 第二轮 ----
    ("叶承福", "李木田", 8, ("李木田", "叶承福", 8)),   # ch8 双向叔侄，"是侄子叶承福"木田为叔
    ("郁公子", "郁萧贵", 309, ("郁萧贵", "郁公子", 319)),  # 309 证据无父子语义系误抽，319 父子边已对
]
ADD = [  # (from名, to名, chapter, kind, evidence)
    ("李通崖", "李清虹", 374, "祖孙",
     "「此乃老祖之孙女、曾孙。」李玄宣颇为自豪地介绍一句（老祖=李通崖，清虹为玄岭之女）"),
    ("郁萧瓯", "郁萧贵", 250, "兄弟",
     "他是郁家萧字辈的大哥…「这个老五，就是个阴沉急迫的性子」（瓯为大哥、贵排行五）"),
]
DEL_EVENT = [  # (from名, to名, chapter) —— 误抽事件删除（边保留）
    ("江雁", "江伯清", 338),   # "父子"事件：338 原文无父子证据（惑我父杀我母者另有其人）
]
MERGE = {  # 碎片名 → 目标名
    "江雁师尊": "江伯清",      # 270 老农/农妇=江伯清易容皮囊
}


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    key = f"{from_id}|{to_id}|{type_}"
    return f"rel_{hashlib.md5(key.encode()).hexdigest()[:12]}"


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    def eid(name: str) -> str | None:
        row = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
        return row["id"] if row else None

    def find_edge(a: str, b: str, ch: int):
        return conn.execute(
            "SELECT * FROM relations WHERE from_id=? AND to_id=? AND chapter=?",
            (eid(a), eid(b), ch)).fetchone()

    # 先做 ADD（DEL 的事件改挂目标可能指向 ADD 的新边）。
    # 注意不用 with 块（退出即自动 commit），dry-run 需在末尾 rollback。
    if True:
        for f, t, ch, kind, ev in ADD:
            fid, tid = eid(f), eid(t)
            if not fid or not tid:
                print(f"  跳过 ADD {f}→{t}：实体缺失")
                continue
            nid = rel_id(fid, tid, "关系")
            if conn.execute("SELECT 1 FROM relations WHERE id=?", (nid,)).fetchone():
                print(f"  跳过 ADD {f}→{t}（{kind}）：边已存在")
                continue
            conn.execute(
                "INSERT INTO relations(id,from_id,to_id,type,attrs_json,chapter,evidence) "
                "VALUES(?,?,?,'关系',?,?,?)",
                (nid, fid, tid, json.dumps({"关系": kind}, ensure_ascii=False), ch, ev))
            print(f"  ADD {f} --{kind}--> {t} (ch{ch})")

        for a, b, ch in [(x[0], x[1], x[2]) for x in SWAP]:
            r = find_edge(a, b, ch)
            if r is None:
                print(f"  跳过 SWAP {a}→{b}(ch{ch})：边不存在（可能已处理）")
                continue
            ai, bi = eid(a), eid(b)
            new_id = rel_id(bi, ai, r["type"])
            dup = conn.execute(
                "SELECT id FROM relations WHERE id=? AND id<>?", (new_id, r["id"])).fetchone()
            if dup:
                # 撞 id：同向已存在 → 删错向边，事件并入保留边
                conn.execute("UPDATE relation_events SET rid=? WHERE rid=?", (dup["id"], r["id"]))
                conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                print(f"  SWAP {a}→{b}(ch{ch}) 撞 {b}→{a} 已有边 → 合并（事件改挂）")
            else:
                conn.execute(
                    "UPDATE relations SET id=?, from_id=?, to_id=? WHERE id=?",
                    (new_id, bi, ai, r["id"]))
                conn.execute(
                    "UPDATE relation_events SET rid=?, from_id=?, to_id=? WHERE rid=?",
                    (new_id, bi, ai, r["id"]))
                print(f"  SWAP {a}→{b}(ch{ch}) → {b}→{a}")

        for a, b, ch, keep in DEL:
            r = find_edge(a, b, ch)
            if r is None:
                print(f"  跳过 DEL {a}→{b}(ch{ch})：边不存在（可能已处理）")
                continue
            keep_id = None
            if keep:
                kr = find_edge(*keep)
                keep_id = kr["id"] if kr else None
            if keep_id:
                conn.execute("UPDATE relation_events SET rid=? WHERE rid=?",
                             (keep_id, r["id"]))
                print(f"  DEL {a}→{b}(ch{ch})，事件改挂 {keep_id}")
            else:
                conn.execute("DELETE FROM relation_events WHERE rid=?", (r["id"],))
                print(f"  DEL {a}→{b}(ch{ch})，事件随删")
            conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))

        for a, b, ch in DEL_EVENT:
            fid, tid = eid(a), eid(b)
            n = conn.execute(
                "SELECT COUNT(*) c FROM relation_events WHERE from_id=? AND to_id=? AND chapter=?",
                (fid, tid, ch)).fetchone()["c"]
            if n:
                conn.execute(
                    "DELETE FROM relation_events WHERE from_id=? AND to_id=? AND chapter=?",
                    (fid, tid, ch))
                print(f"  DEL_EVENT {a}↔{b} ch{ch}：删 {n} 条事件")
            else:
                print(f"  跳过 DEL_EVENT {a}↔{b}(ch{ch})：无事件")

        for frag, target in MERGE.items():
            fbid, tgid = eid(frag), eid(target)
            if not fbid or not tgid or fbid == tgid:
                print(f"  跳过 MERGE {frag}→{target}：缺失或已合并")
                continue
            for r in conn.execute(
                "SELECT * FROM relations WHERE from_id=? OR to_id=?", (fbid, fbid)).fetchall():
                nf = tgid if r["from_id"] == fbid else r["from_id"]
                nt = tgid if r["to_id"] == fbid else r["to_id"]
                nid = rel_id(nf, nt, r["type"])
                hit = conn.execute("SELECT 1 FROM relations WHERE id=?", (nid,)).fetchone()
                if hit:
                    conn.execute("UPDATE relation_events SET rid=? WHERE rid=?",
                                 (nid, r["id"]))
                    conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                else:
                    conn.execute("UPDATE relations SET id=?, from_id=?, to_id=? WHERE id=?",
                                 (nid, nf, nt, r["id"]))
            conn.execute("UPDATE relation_events SET from_id=? WHERE from_id=?", (tgid, fbid))
            conn.execute("UPDATE relation_events SET to_id=? WHERE to_id=?", (tgid, fbid))
            for al in conn.execute(
                "SELECT alias FROM aliases WHERE entity_id=?", (fbid,)).fetchall():
                conn.execute("INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)",
                             (tgid, al["alias"]))
            for c in conn.execute(
                "SELECT dimension,value FROM classifications WHERE entity_id=?",
                (fbid,)).fetchall():
                conn.execute(
                    "INSERT OR IGNORE INTO classifications(entity_id,dimension,value) "
                    "VALUES(?,?,?)", (tgid, c["dimension"], c["value"]))
            b_attrs = json.loads(conn.execute(
                "SELECT attrs_json FROM entities WHERE id=?", (fbid,)
            ).fetchone()["attrs_json"] or "{}")
            g_json = conn.execute(
                "SELECT attrs_json FROM entities WHERE id=?", (tgid,)).fetchone()["attrs_json"]
            conn.execute("UPDATE entities SET attrs_json=? WHERE id=?",
                         (json.dumps({**b_attrs, **json.loads(g_json or "{}")},
                                     ensure_ascii=False), tgid))
            conn.execute("DELETE FROM entities WHERE id=?", (fbid,))
            conn.execute("DELETE FROM aliases WHERE entity_id=?", (fbid,))
            conn.execute("DELETE FROM classifications WHERE entity_id=?", (fbid,))
            print(f"  MERGE {frag} → {target}（关系/事件/别名/分类/attrs 已迁移）")

    if dry:
        conn.rollback()
        print("（dry-run，以上操作已回滚）")
    else:
        conn.commit()
        print("落库完成")


if __name__ == "__main__":
    main()

"""2026-08-21 通用别名碎片合并脚本（每批章节跑完后的人工核查修正）。

MERGE（碎片名 → 目标名）：别名/分类/关系/事件全部迁移到目标实体，
碎片名写入目标 aliases（重放时别名机制自动归并，raw_json 无需改写）。
RENAME（旧名 → 新名）：无目标实体的改名（如简称先建了实体），改名后
新旧名都写入 aliases，重放两侧都能归并。
DELETE（泛称/误抽名）：实体+关系+事件删除，并从 raw_json 剔除相关条目（防重放复活）。
ALIAS_DROP（实体名, 误写别名）：从实体 aliases 剔除，并同步剔除 raw_json（防复活）。

用法：
    .venv/bin/python scripts/merge_alias_fragments.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys

# 2026-08-21 批次1（76-100 章）人工核查结论：
# - 羽楔/于羽楔：同一人，81章司元白"羽楔被派去凑太阴月华"= 87章"筑基修士于羽楔吞服太阴月华战死倚山城"
# - 玄岭/李玄岭：同一人，91-96章两词同频共现，93章"玄岭"为单独简称
# - 漆黑长弓/黝黑长弓：同一把弓（李玄锋），84章"黝黑的长弓"= 94章"漆黑长弓"
# - 金丹黄箓/黄箓：同一枚箓，95章"远方大山深处的黄箓(金丹级)"= 96章"大厥庭方向那枚金丹黄箓"；
#   主名取"黄箓"与既有"灰箓"（箓气灰白青黄对应练气筑基紫府金丹）命名风格一致
# - 箓气/灰箓：同一枚，97章"李项平受的箓气避死延生"= 85章凝出赐下的灰箓
# 2026-08-21 批次2（101-125 章）人工核查结论：
# - 巫术咒杀/咒杀：同一术法同一事件（箓巫咒杀李项平，100章建"咒杀"、102章重复建）
# - 剑气/玄水剑气：同一术法，107章李通崖"使出剑气来劈砍"即其唯一剑气类术法（94章玄水剑气）
# - 长枪/雪白长枪：同一把，104章蛇洞地面"雪白的长枪"= 105章"蛇洞中所得…雪白发亮枪身浮现电芒"
# 排除项（核查过不并）：东山越≠山越（109章"也称东山越"是木焦蛮整合势力别称）；
# 紫府中年人≠中年人（不同角色）；青乌长棍≠长棍（不同物）；大黎山狐族/望月湖底洞府为部分-整体关系
# 2026-08-22 批次3（177-276 章）人工核查结论：
# - 杂气/唦摩里的杂气：同一道，174章"那份唦摩里的杂气"=177章"存放着一道杂气…为那唦摩里准备"=223章"当年唦摩里吞服杂气"
# - 蛟少爷、蛟哥/李渊蛟：185章"我那蛟弟"、193章"蛟哥带着兵打了数月的山越"（渊蛟统兵山越），186章李渊蛟自带别名蛟少爷
# - 项平公/李项平：171章"大父同项平公一同殒命山越"，184章李项平自带别名项平公
# - 慕仙/郁慕仙：184章"我写信问一问慕仙"，246章郁慕仙自带别名慕仙
# - 慕剑/郁慕剑：195章"四哥…往北方去了"=245章"郁慕剑…往北边镗金门的方向去了"
# - 如誉/萧如誉：196章"雍灵同李通崖的关系…如誉和李玄锋也有交情"，萧李两家人物对举
# - 归鸾/萧归鸾：228章萧归图"归鸾正是舍妹"，236章"归鸾…说是愿意嫁"配李渊蛟
# - 渊平/李渊平：204章"宣儿抱上来的渊平"=203章"叫渊平吧，李渊平"（玄宣之子）
# - 清晓/李清晓：239章"回去看看景恬和清晓"=212章"李景恬诞下的女儿，唤作李清晓"（陈冬河入赘所出）
# - 冬河叔/陈冬河：210章"冬河叔还在上山"=188章"冬河，你且驾风往郡中去"
# - 剑仙、李尺剑仙/李尺泾：249章"可李尺泾是剑仙"、253章"当年剑仙归家…送他归来黎泾"、272章李尺泾自带别名剑仙；227章"讨好那李尺……剑仙"断行错拆
# - 妖王/南疆妖王：273章"邓求之与剑仙…陨落南疆，为妖王所食"=205章李尺泾身亡南疆
# - 妖洞/大黎山妖洞：224章宝药"记在妖洞的帐上"、259章"大黎山是妖洞的地盘"
# - 大徐/徐国：190章"往北的大徐"、259章徐国自带别名大徐（镗金门位处徐国）
# - 玉庭戍/玉庭山：242章"其一曰玉庭山"，253章玉庭山自带别名玉庭戍
# - 庭上红尘/庭上红尘气：250章"失了那一气「庭上红尘」"=210章"须要庭上红尘气来修炼"
# - 寒甲气/庭下寒甲气：254章"提炼那庭下寒甲气"
# - 安鹧/安鹧言：254章"据安鹧言所说"错拆出半名人名
# - 合清/郁萧瓯：250章"十五岁的郁萧瓯被迷得神魂颠倒，他挽起她的长发，叫她合清"（老翁对她的称呼）
# - 木田叔/李木田：234章"主家人的性格都渊源与木田叔"，即2章出场的李氏 patriarch 李木田
# 排除项（核查过不并）：仙人(187)≠白发仙人(108)（端木奎遇仙与北麓狐族传说无文本关联）；
# 小盾(188)≠白玉色小盾(42)/白色小盾(43)（188是李家法器实物，42-43是万萧华法诀盾）；
# 老翁(206)≠镇虺观老翁(264)（望月湖船翁 vs 徐国老修）；田叔(3)≠李木田（3章"村里人中田叔最厚道"是村民）；
# 大巫祝(183)≠阿会剌≠木焦蛮（183被李妃若杀的是"荠木的巫祝"184章，阿会剌是唦摩里麾下大巫祝且256章健在，木焦蛮是王非巫祝）；
# 仙人/银子/名册/药囊等泛指道具暂留待后续清理；十六妖洞(262)是设想未建组织保留
MERGE = {
    "羽楔": "于羽楔",
    "玄岭": "李玄岭",
    "漆黑长弓": "黝黑长弓",
    "金丹黄箓": "黄箓",
    "箓气": "灰箓",
    "巫术咒杀": "咒杀",
    "剑气": "玄水剑气",
    "长枪": "雪白长枪",
    # —— 批次3（177-276 章）——
    "杂气": "唦摩里的杂气",
    "蛟少爷": "李渊蛟",
    "蛟哥": "李渊蛟",
    "项平公": "李项平",
    "慕仙": "郁慕仙",
    "慕剑": "郁慕剑",
    "如誉": "萧如誉",
    "归鸾": "萧归鸾",
    "渊平": "李渊平",
    "清晓": "李清晓",
    "冬河叔": "陈冬河",
    "剑仙": "李尺泾",
    "李尺剑仙": "李尺泾",
    "妖王": "南疆妖王",
    "妖洞": "大黎山妖洞",
    "大徐": "徐国",
    "玉庭戍": "玉庭山",
    "庭上红尘": "庭上红尘气",
    "寒甲气": "庭下寒甲气",
    "安鹧": "安鹧言",
    "合清": "郁萧瓯",
    "木田叔": "李木田",
}
# 黎山(78) 是"黎泾山"口语简称（原文两词混用指同一座山），库中无黎泾山实体，改名建主名
# 批次3：如怜=萧家女（197章萧元思家议嫁，与如誉=萧如誉同族同式，库中无萧如怜实体）
# 大巫祝(183)=被李妃若杀的荠木巫祝（184章"荠木的巫祝与走狗忠余歹，皆已伏诛"），改全名与"大巫祝"称谓（阿会剌）区分
# 合干(249)=蒋合干（250章"蒋合干狞笑"，蒋家客卿），库中无蒋合干实体
RENAME = {
    "黎山": "黎泾山",
    # —— 批次3（177-276 章）——
    "如怜": "萧如怜",
    "大巫祝": "荠木巫祝",
    "合干": "蒋合干",
}

# 批次3 误抽删除（泛称/称谓类别，非实体；删后从 raw_json 剔除防重放复活）：
# - 渊清：辈分统称"渊清辈"（222章"渊清辈中的第一人"、256章"渊清辈也应就我们几个了"），非人物
# - 曦月：下一辈分统称"曦月辈"（221章"渊字辈领头的"、227章"曦月辈的第一批子弟"），非人物
# - 怜愍、摩诃：释教大能的称谓类别（231章"释教也有大能出手，什么怜愍、摩诃"、270章"作摩诃的年年岁岁作摩诃"），非具体人物
DELETE = ["渊清", "曦月", "怜愍", "摩诃"]

# 批次3 别名剔除（LLM 把驻地/术法/同段落人物误写进 aliases；剔后从 raw_json 同步剔除防复活）：
# - 费家 ← 寒云峰：211章"费家，寒云峰"是场景对举（费家盘踞寒云峰），峰本身另有实体
# - 迟尉 ← 如重浊：220章"他的命神通『如重浊』"是术法名，术法另有实体
# - 木焦蛮 ← 大巫祝：185章同段混淆；木焦蛮是荠木之王（183章"生前"、184章"在位之时"），大巫祝另有其人
ALIAS_DROP = [
    ("费家", "寒云峰"),
    ("迟尉", "如重浊"),
    ("木焦蛮", "大巫祝"),
]


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

    def migrate(bad: str, good: str) -> None:
        """把 bad 实体的关系/事件/别名/分类/attrs 全部迁到 good，删 bad 行。"""
        for r in conn.execute(
            "SELECT * FROM relations WHERE from_id=? OR to_id=?", (bad, bad)
        ).fetchall():
            nf = good if r["from_id"] == bad else r["from_id"]
            nt = good if r["to_id"] == bad else r["to_id"]
            nid = rel_id(nf, nt, r["type"])
            hit = conn.execute("SELECT 1 FROM relations WHERE id=?", (nid,)).fetchone()
            if hit:
                conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
            else:
                conn.execute(
                    "UPDATE relations SET id=?, from_id=?, to_id=? WHERE id=?",
                    (nid, nf, nt, r["id"]),
                )
        conn.execute("UPDATE relation_events SET from_id=? WHERE from_id=?", (good, bad))
        conn.execute("UPDATE relation_events SET to_id=? WHERE to_id=?", (good, bad))
        for a in conn.execute("SELECT alias FROM aliases WHERE entity_id=?", (bad,)).fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)", (good, a["alias"])
            )
        for c in conn.execute(
            "SELECT dimension,value FROM classifications WHERE entity_id=?", (bad,)
        ).fetchall():
            conn.execute(
                "INSERT OR IGNORE INTO classifications(entity_id,dimension,value) VALUES(?,?,?)",
                (good, c["dimension"], c["value"]),
            )
        b_attrs = json.loads(
            conn.execute("SELECT attrs_json FROM entities WHERE id=?", (bad,))
            .fetchone()["attrs_json"]
            or "{}"
        )
        g_json = conn.execute("SELECT attrs_json FROM entities WHERE id=?", (good,)).fetchone()[
            "attrs_json"
        ]
        merged = {**b_attrs, **json.loads(g_json or "{}")}
        conn.execute(
            "UPDATE entities SET attrs_json=? WHERE id=?",
            (json.dumps(merged, ensure_ascii=False), good),
        )
        conn.execute("DELETE FROM entities WHERE id=?", (bad,))
        conn.execute("DELETE FROM aliases WHERE entity_id=?", (bad,))
        conn.execute("DELETE FROM classifications WHERE entity_id=?", (bad,))

    plan_merge = []
    for frag, target in MERGE.items():
        b, g = eid(frag), eid(target)
        if b and g and b != g:
            plan_merge.append((frag, b, target, g))
        else:
            print(f"  跳过 {frag}（碎片/目标缺失或同 id）")

    plan_rename = []
    for old, new in RENAME.items():
        o = eid(old)
        if o and eid(new) is None:
            plan_rename.append((old, o, new))
        else:
            print(f"  跳过改名 {old}（缺失或新名已存在）")

    plan_del = [(n, eid(n)) for n in DELETE if eid(n)]
    plan_alias_drop = []
    for name, alias in ALIAS_DROP:
        i = eid(name)
        if i:
            plan_alias_drop.append((name, i, alias))
        else:
            print(f"  跳过剔别名 {name}（实体缺失）")

    print(f"待合并 {len(plan_merge)}：{[(f, t) for f, _, t, _ in plan_merge]}")
    print(f"待改名 {len(plan_rename)}：{[(o, n) for o, _, n in plan_rename]}")
    print(f"待删除 {len(plan_del)}：{[n for n, _ in plan_del]}")
    print(f"待剔别名 {len(plan_alias_drop)}：{plan_alias_drop}")
    if dry:
        return

    with conn:
        for frag, bad, target, good in plan_merge:
            # 碎片名入目标 aliases（重放归并的关键），先加再迁（别名随迁不丢）
            conn.execute("INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)", (good, frag))
            migrate(bad, good)
            print(f"  合并 {frag} -> {target}")
        for old, bad, new in plan_rename:
            conn.execute("UPDATE entities SET name=? WHERE id=?", (new, bad))
            conn.execute("INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)", (bad, new))
            conn.execute("INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)", (bad, old))
            print(f"  改名 {old} -> {new}")
        # 删除泛称/误抽：实体+关系+事件（raw_json 在下方统一剔除防重放复活）
        for name, bad in plan_del:
            conn.execute("DELETE FROM relations WHERE from_id=? OR to_id=?", (bad, bad))
            conn.execute("DELETE FROM relation_events WHERE from_id=? OR to_id=?", (bad, bad))
            conn.execute("DELETE FROM entities WHERE id=?", (bad,))
            conn.execute("DELETE FROM aliases WHERE entity_id=?", (bad,))
            conn.execute("DELETE FROM classifications WHERE entity_id=?", (bad,))
            print(f"  删除 {name}")
        # 剔除误写别名
        for name, i, alias in plan_alias_drop:
            conn.execute("DELETE FROM aliases WHERE entity_id=? AND alias=?", (i, alias))
            print(f"  剔别名 {name} <- {alias}")
        # raw_json 剔除 DELETE 实体及其关系 + ALIAS_DROP 别名（重放时不再复活）
        for row in conn.execute("SELECT chapter, raw_json FROM extractions").fetchall():
            data = json.loads(row["raw_json"])
            ents = [e for e in data.get("entities", []) if e.get("name") not in DELETE]
            rels = [
                r for r in data.get("relations", [])
                if r.get("from_name") not in DELETE and r.get("to_name") not in DELETE
            ]
            changed = len(ents) != len(data.get("entities", [])) or len(
                rels
            ) != len(data.get("relations", []))
            drop_map = dict(ALIAS_DROP)
            for e in ents:
                bad_alias = drop_map.get(e.get("name"))
                if bad_alias and bad_alias in (e.get("aliases") or []):
                    e["aliases"] = [a for a in e["aliases"] if a != bad_alias]
                    changed = True
            if changed:
                data["entities"], data["relations"] = ents, rels
                conn.execute(
                    "UPDATE extractions SET raw_json=? WHERE chapter=?",
                    (json.dumps(data, ensure_ascii=False), row["chapter"]),
                )
    print("落库完成")

    names = list(MERGE) + list(MERGE.values()) + list(RENAME) + list(RENAME.values())
    q = "('" + "','".join(names) + "')"
    for row in conn.execute(f"SELECT name, type, first_chapter FROM entities WHERE name IN {q}"):
        print(f"  {row['name']} [{row['type']}] 首现{row['first_chapter']}章")
    left = conn.execute(
        f"SELECT COUNT(*) c FROM entities WHERE name IN ('" + "','".join(MERGE) + "')"
    ).fetchone()["c"]
    print(f"  碎片残留: {left}")


if __name__ == "__main__":
    main()

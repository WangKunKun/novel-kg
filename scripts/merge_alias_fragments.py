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
    # —— 批次4（277-351 章）——
    "莲花宗": "莲花寺",  # ch281"莲花宗乃是法相道统"=ch283"莲花寺位处赵国…前十的大寺院"，同一处（老祖堇莲摩诃）
    "法慧法师": "法慧",  # ch287"小僧短陈寺法慧"与ch303同一人，全称/尊称碎片
    "金殿": "黄金大殿",  # 明慧法器：ch280"祭炼了法器，乃是一座黄金大殿"=ch281"那金殿…金殿法器"
    "玉庭峰": "玉庭山",  # ch288"我家吞下了玉庭山"=ch290"玉庭峰回禀"，李家新吞之地的峰/山混称
    "东山越之地": "东山越",  # ch288"去了东山越之地"是地域指称，并入东山越势力
    "紫府": "紫府渔翁",  # ch295"那紫府要我前去落霞山"=押送李玄岭的蓑衣老翁（ch292-294江岸渔翁，尊称"司前辈"）
    "上元": "上元真人",  # ch298"总不可能是上元道友"即ch230已有的上元真人（ch298"上元是剑仙"）
    "上元剑仙": "上元真人",  # ch331"那上元剑仙、萧初庭"=ch298"上元是剑仙又不是巫仙"
    "曦峸": "李曦峸",  # ch310 李曦峸自带别名曦峸，ch313 简称重抽
    "曦峻": "李曦峻",  # ch323 李曦峻自带别名曦峻，ch341 简称重抽
    "治儿": "李曦治",  # ch344"剑道天赋最好的治儿去了宗内"=ch274 李曦治（ch347"曦治的名字是归鸾想的"、ch349 随袁湍修行）
    "慕容大人": "慕容夏",  # ch283"让你去护送慕容大人"即魔修慕容夏（ch279 被护送南下者）
    "木田前辈": "李木田",  # ch326"木田前辈…恐怕不是简单的筑基"=李家老祖李木田
    "木田老祖": "李木田",  # ch333"高祖乃是木田老祖之庶弟"=ch335"我家传自木田老祖"，李木田已自带别名老祖
    "青穗峰主": "袁湍",  # ch322"青穗峰袁湍…接替青穗峰峰主之位"，袁湍 ch22 已有实体
    "仲青": "田仲青",  # ch326 简称重抽，田仲青 ch192 已有
    "逍金": "逍金真君",  # ch334/ch335 同一位真君的简称/全称
    "步梓": "步梓真人",  # ch331 简称重抽，步梓真人 ch230 已有
    "云拢天南大阵": "云拢天南阵",  # 费家镇族大阵：ch311【云拢天南阵】(=护山大阵/镇族大阵)=ch316 云拢天南大阵
    "费氏": "费家",  # ch318"费氏无咎"=费家别称
    "燕赵": "燕赵之国",  # ch325"北方大国唯有燕赵"=ch190 燕赵之国
    "王氏": "颍华王家",  # ch334 颍华王家自带别名王氏/王家，ch335 重抽
    "摩诃": "法慧",  # ch280-306 的"摩诃"即忿怒摩诃九世=法慧宿体：ch296"忿怒摩诃已经修了九世…在法慧身上彻底苏醒"、
                       # ch301"九世摩诃…岂是你等可以揣摩的"（忿怒摩诃自道）、ch306"老祖剑斩摩诃"；
                       # 其 13 条关系（持有花纹短棍/施展怒目相/所属短陈寺/对李通崖等）10 余条均属法慧。
                       # 注：ch280"明慧师从摩诃""妖物在师尊座下受教诲"之"摩诃"实为堇莲摩诃，归并后这两条
                       # "关系"型边指向法慧属已知偏差（脚本不支持改指，留档）
    "摩诃转世": "法慧",  # ch305-307"摩诃转世…这样的对手怎么能轻易斩杀"即剑斩之摩诃（忿怒摩诃九世）
    "怒目法": "怒目四魔帝刹相",  # ch287"法慧师兄练的乃是怒目法"=ch300"本尊的怒目四魔帝刹相"，同一功法的阶段称
    "怒目相伏魔天地": "怒目四魔帝刹相",  # ch301"早就练就了怒目相伏魔天地"即怒目相金身展开的伏魔场域
    "黑色葫芦": "墨色葫芦",  # ch289"墨色的葫芦"收尸骨怨气（江雁案），ch290 隔章重抽
    "玉杵": "碧玉杵",  # ch343 于家药铺"一根玉杵"，ch347 李渊蛟命名【碧玉杵】
    "药臼": "碧玉臼",  # ch343"缺了口的翠绿色药臼"，ch347 命名【碧玉臼】
    "灵猴": "白猴",  # ch343 救下的于家捣药灵猴=ch347"洗去了一身炭灰，浑身毛发雪白"的老猴
    "善修禅教": "禅教",  # ch279"善修禅教，竟然庇护一魔修食人"是对禅教的讽称，非新教派
    "北方释教": "释教",  # ch337"北方释教是上下死气沉沉"=ch190 释教（释教本在北方）
}
# 黎山(78) 是"黎泾山"口语简称（原文两词混用指同一座山），库中无黎泾山实体，改名建主名
# 批次3：如怜=萧家女（197章萧元思家议嫁，与如誉=萧如誉同族同式，库中无萧如怜实体）
# 大巫祝(183)=被李妃若杀的荠木巫祝（184章"荠木的巫祝与走狗忠余歹，皆已伏诛"），改全名与"大巫祝"称谓（阿会剌）区分
# 合干(249)=蒋合干（250章"蒋合干狞笑"，蒋家客卿），库中无蒋合干实体
# 批次4：慕年=郁家人（315章"慕年大人说是李家毫无动静"），循 慕仙→郁慕仙 家族命名式，库中无郁慕年实体
RENAME = {
    "黎山": "黎泾山",
    # —— 批次3（177-276 章）——
    "如怜": "萧如怜",
    "大巫祝": "荠木巫祝",
    "合干": "蒋合干",
    # —— 批次4（277-351 章）——
    "慕年": "郁慕年",
}

# 批次3 误抽删除（泛称/称谓类别，非实体；删后从 raw_json 剔除防重放复活）：
# - 渊清：辈分统称"渊清辈"（222章"渊清辈中的第一人"、256章"渊清辈也应就我们几个了"），非人物
# - 曦月：下一辈分统称"曦月辈"（221章"渊字辈领头的"、227章"曦月辈的第一批子弟"），非人物
# - 怜愍：释教境界称谓（283章"再修成怜愍，又低了紫府几分"——法师→怜愍→摩诃→法相），非具体人物；279章重抽
# 批次4 更正：摩诃从 DELETE 改为 MERGE→法慧 —— 277-306 章的"摩诃"具体指忿怒摩诃九世（=法慧宿体），
# 且 ch280 重建的摩诃实体挂了 13 条关系（持有花纹短棍/所属短陈寺/对李通崖等）绝大多数属法慧，删除会连边丢失；
# "摩诃"作为境界名仅在旁白释修体系时出现（283章），抽取器极少单独抽出，别名归并副作用可控。
DELETE = ["渊清", "曦月", "怜愍"]

# 批次3 别名剔除（LLM 把驻地/术法/同段落人物误写进 aliases；剔后从 raw_json 同步剔除防复活）：
# - 费家 ← 寒云峰：211章"费家，寒云峰"是场景对举（费家盘踞寒云峰），峰本身另有实体
# - 迟尉 ← 如重浊：220章"他的命神通『如重浊』"是术法名，术法另有实体
# - 木焦蛮 ← 大巫祝：185章同段混淆；木焦蛮是荠木之王（183章"生前"、184章"在位之时"），大巫祝另有其人
# 批次4（277-351 章）：
# - 山越国 ← 东山越/山越/西山越：306章"诸修瓜分山越，各自建立了西山越、山越国…我这东山越"——三者是山越
#   灭后并立的兄弟势力，非一国别名（东山越、山越另有实体；332章山越督、331章田氏/李寄蛮争的即山越国）
# - 玉符 ← 玉佩：279章"李清虹捏碎了求救的玉符"是求救符，非 22 章的玉佩
# - 猪二 ← 猪妖：350章"说是嗒朱洞中的妖兵"（练气巅峰），非大黎山北麓的筑基猪妖（20章，猪妖另有实体）
# - 法慧 ← 怒目相：摩诃→法慧 归并带入的别名；怒目相是术法相貌名，归 怒目四魔帝刹相（术法）更当
ALIAS_DROP = [
    ("费家", "寒云峰"),
    ("迟尉", "如重浊"),
    ("木焦蛮", "大巫祝"),
    # —— 批次4（277-351 章）——
    ("山越国", "东山越"),
    ("山越国", "山越"),
    ("山越国", "西山越"),
    ("玉符", "玉佩"),
    ("猪二", "猪妖"),
    ("法慧", "怒目相"),
]

# 批次4 排除项（核查过不并）：
# - 明慧(279)≠法慧(287)：明慧是莲花寺首徒/堇莲摩诃弟子（283章），法慧是短陈寺僧/忿怒摩诃宿体（287章）
# - 堇莲摩诃(281)≠法慧：莲花宗老祖七世摩诃（283章"轮回七世"），非剑斩之摩诃（九世忿怒摩诃）
# - 青宣(333)≠青宣岳(322)：前者是袁湍赠李曦明的护身法器【青宣】（化鹰犬虎鹿），后者是袁湍仙基名
# - 灵水(329)≠清元灵水(207)≠天地灵水(347)：白衣少年（李氏先祖）尸解所化的青湛之水 / 渌水真君灵水 / 瓶装寒水宝物
# - 玉杵族之青色玉盒(338)≠玉盒(46)、灰色地图(338)≠地图(24)、金色符箓(299)≠符箓(4)：同名不同物
# - 鬣犬(351)≠灰色鬣犬(174)/鬣犬妖(175)：嗒朱洞新入伙的妖物（351章"新入洞不久"），非李玄锋早年在黎泾所遇群犬
# - 宁师兄(339)≠宁和远(310)：青池门内弟子尊称 vs 上门挑战的散修剑修，无文本关联
# - 唐师兄(293)≠唐元乌(331)：与郁慕仙论金销洞者 vs 北方名人列举，无直接证据
# - 老夫人(282)/黑衣修士(289)/黑衣男子(312)/萧家修士(342)：未具名但指称具体的角色，留待后文命名再定
# - 大陵(347)是道统（"大陵道统绝矣"），与功法"江河大陵经"分立


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
            drop_map: dict[str, list[str]] = {}
            for name, alias in ALIAS_DROP:
                drop_map.setdefault(name, []).append(alias)
            for e in ents:
                bad = [a for a in drop_map.get(e.get("name"), []) if a in (e.get("aliases") or [])]
                if bad:
                    e["aliases"] = [a for a in e["aliases"] if a not in bad]
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

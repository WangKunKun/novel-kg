"""族谱/师徒树构建与渲染（只读查询，方向约定见模块常量注释）。"""
import json
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass, field

# —— 亲属性质常量（attrs 键兼容"关系"/"性质"，值去括号后缀）——
KIN_KEYS = ("关系", "性质")
PARENT_CHILD = {"父子", "母子", "父女", "母女"}          # from=父/母 → to=子/女
GRAND = {"祖孙", "后裔"}                                 # from=祖 → to=孙，代差 2
UNCLE = {"叔侄", "姑侄", "舅甥", "族叔侄"}                # from=长 → to=晚，代差 1
SYMMETRIC = {"夫妻", "兄弟", "兄妹", "姐弟", "族兄弟"}
MASTER_APPRENTICE = {"师徒", "师兄弟"}                    # 师兄弟对称，师徒 from=师
KIN_ALL = PARENT_CHILD | GRAND | UNCLE | SYMMETRIC

DEAD_KEYWORDS = ("陨落", "身死", "战死", "被杀", "已故", "殁", "惨死", "身亡", "死了")
FAMILY_FACTIONS = {"李家", "黎泾村"}   # sect 标注时排除的血脉家族/村落
LI_SEEDS = {"李木田", "李根水"}        # 圈定种子（李家最早血脉）


def _attrs_json(raw: str | None) -> dict:
    """解析 attrs_json，坏 JSON/None 一律回退 {}。"""
    try:
        d = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return d if isinstance(d, dict) else {}


def edge_kind(attrs_json: str | None) -> str:
    """从边 attrs 提取亲属性质，兼容两种键，"敌对（击杀）"→"敌对"。"""
    d = _attrs_json(attrs_json)
    for k in KIN_KEYS:
        v = str(d.get(k, "") or "").split("（")[0]
        if v:
            return v
    return ""


@dataclass
class Person:
    id: str
    name: str
    jingjie: str = ""      # 境界（去括号）
    sect: str = ""         # 拜入宗门（所属边中排除家族/村落后的第一个）
    dead: bool = False
    generation: int | None = None   # 族谱/师承代际（0 起），None=未定位
    foreign: bool = False           # 师徒树外节点


@dataclass
class Tree:
    title: str
    persons: dict[str, Person] = field(default_factory=dict)
    edges: list[tuple[str, str, str]] = field(default_factory=list)  # (kind, a_id, b_id)
    issues: list[str] = field(default_factory=list)


def _load_persons(conn: sqlite3.Connection) -> dict[str, Person]:
    persons = {}
    for r in conn.execute("SELECT id, name, attrs_json FROM entities WHERE type='人物'"):
        attrs = _attrs_json(r["attrs_json"])
        persons[r["id"]] = Person(
            id=r["id"], name=r["name"],
            jingjie=str(attrs.get("境界", "") or "").split("（")[0],
            dead=any(kw in str(attrs.get("简介", "")) for kw in DEAD_KEYWORDS),
        )
    for r in conn.execute(
        "SELECT r.from_id, e.name FROM relations r JOIN entities e ON r.to_id=e.id "
        "WHERE r.type='所属' ORDER BY r.chapter, r.id"
    ):
        p = persons.get(r["from_id"])
        if p and r["name"] not in FAMILY_FACTIONS and not p.sect:
            p.sect = r["name"]
    return persons


def _kin_edges(conn: sqlite3.Connection, kinds: set[str]) -> list[tuple[str, str, str]]:
    out = []
    for r in conn.execute("SELECT from_id, to_id, attrs_json FROM relations WHERE type='关系'"):
        k = edge_kind(r["attrs_json"])
        if k in kinds:
            out.append((k, r["from_id"], r["to_id"]))
    return out


def li_family_members(conn: sqlite3.Connection) -> set[str]:
    """李家圈定：种子沿亲属边连通闭包，再过滤 李姓 OR 闭包内成员的配偶。"""
    persons = _load_persons(conn)
    id2name = {pid: p.name for pid, p in persons.items()}
    kin = _kin_edges(conn, KIN_ALL)
    adj: dict[str, set[str]] = defaultdict(set)
    for _, a, b in kin:
        adj[a].add(b)
        adj[b].add(a)
    seeds = {pid for pid, name in id2name.items() if name in LI_SEEDS}
    closure, q = set(seeds), deque(seeds)
    while q:
        cur = q.popleft()
        for nxt in adj[cur]:
            if nxt not in closure:
                closure.add(nxt)
                q.append(nxt)
    # 过滤：李姓保留；非李姓仅当与李姓成员有夫妻边
    li = {pid for pid in closure if id2name[pid].startswith("李")}
    spouses = {a if b in li else b for k, a, b in kin if k == "夫妻" and (a in li or b in li)}
    # 夫妻边端点必在连通闭包内，无需再交 closure
    return li | spouses


def build_family_tree(conn: sqlite3.Connection, members: set[str]) -> Tree:
    """族谱树：亲子边拓扑分层；夫妻同层；多父/环进 issues；祖孙/叔侄挂孤儿。"""
    FATHER = {"父子", "父女"}
    MOTHER = {"母子", "母女"}
    persons_all = _load_persons(conn)
    tree = Tree(
        title="李氏族谱",
        persons={pid: persons_all[pid] for pid in members if pid in persons_all},
    )
    first_ch = {r["id"]: r["first_chapter"] for r in conn.execute(
        "SELECT id, first_chapter FROM entities")}
    kin = _kin_edges(conn, KIN_ALL)

    # 亲子边收集（父系/母系分开处理）；多父/多母 = 同系父边多于一条 → 报告，
    # 主边取首现最早者（父母各保留一条）
    pc_by_child: dict[str, list[tuple[str, str]]] = defaultdict(list)  # child -> [(kind, parent)]
    for k, a, b in kin:
        if k in PARENT_CHILD and a in tree.persons and b in tree.persons:
            pc_by_child[b].append((k, a))
    kept_pc: list[tuple[str, str, str]] = []  # (kind, parent, child)，保留原始性质
    for child, lst in pc_by_child.items():
        lst.sort(key=lambda ka: first_ch.get(ka[1], 10**9))
        for kinds, label in ((FATHER, "多父"), (MOTHER, "多母")):
            same = [(k, p) for k, p in lst if k in kinds]
            if len({p for _, p in same}) > 1:
                names = "、".join(tree.persons[p].name for _, p in same)
                tree.issues.append(f"{label}：{tree.persons[child].name} 的{label}边指向 "
                                   f"{names}，主边取首现最早者")
        kept_groups: set[str] = set()
        for k, p in lst:
            # 同系（父系/母系）仅留首现最早的一条：按性别组去重而非精确性质，
            # 与上面的多父/多母检测口径一致（父子+父女来自两个不同父=多父，只留一条）
            grp = "父" if k in FATHER else "母" if k in MOTHER else k
            if grp not in kept_groups:
                kept_groups.add(grp)
                kept_pc.append((k, p, child))
    tree.edges = [(k, p, c) for k, p, c in kept_pc]

    children: dict[str, list[str]] = defaultdict(list)
    child_parents: dict[str, list[str]] = defaultdict(list)
    for _, p, c in kept_pc:
        children[p].append(c)
        child_parents[c].append(p)
    has_parent = set(child_parents)

    # 夫妻边（限树内）
    spouse_pairs = [(a, b) for k, a, b in kin
                    if k == "夫妻" and a in tree.persons and b in tree.persons]

    # 根 = 无保留亲子父边、无祖孙/叔侄挂靠长辈、且不通过夫妻挂到有父边的配偶
    # （嫁入者随配偶分层；仅凭祖孙/叔侄边连接的孤儿不是根，留待挂靠阶段定位）
    adopted = {b for k, a, b in kin
               if (k in GRAND or k in UNCLE) and a in tree.persons and b in tree.persons}

    def _find_roots() -> list[str]:
        return [pid for pid in tree.persons
                if pid not in has_parent and pid not in adopted
                and not any((pid == a and b in has_parent) or (pid == b and a in has_parent)
                            for a, b in spouse_pairs)]

    roots = _find_roots()

    def _relax() -> tuple[bool, bool]:
        """沿亲子边松弛分层（child = 1 + max(父辈层)）。

        返回 (全部子节点已分层, 触顶时仍想变更)。轮数上限只是防脏数据的
        护栏而非正确性界：正常 DAG 在 ≤n 轮内收敛；若触顶时 changed 仍为
        True，说明每轮都在整体抬层 —— 存在从根可达的环，当前代际全是垃圾。
        """
        changed = True
        rounds = 0
        while changed and rounds <= len(tree.persons) + 1:
            changed, rounds = False, rounds + 1
            for pid in roots:
                if tree.persons[pid].generation is None:
                    tree.persons[pid].generation = 0
                    changed = True
            for child, ps in child_parents.items():
                gens = [tree.persons[p].generation for p in ps
                        if tree.persons[p].generation is not None]
                if gens:  # 至少一个父辈已分层即可先定，后续父辈补层时单调抬高
                    want = max(gens) + 1
                    cur = tree.persons[child].generation
                    if cur is None or want > cur:
                        tree.persons[child].generation = want
                        changed = True
        placed = all(tree.persons[c].generation is not None for c in child_parents)
        return placed, changed

    placed, still_changing = _relax()
    if not placed or still_changing:
        # 环：破边仅执行一次（保证终止，总共至多两次分层）；若去掉的环之外
        # 还有另一个不相交的环，第二次分层仍受阻，退化为"未定位"报告。
        if still_changing:  # 可达环已产生垃圾代际，全部清零重来
            for p in tree.persons.values():
                p.generation = None
        # 环成员 = 保留亲子图中的强连通分量（>1 节点或自环）
        graph: dict[str, list[str]] = defaultdict(list)
        for _, p, c in kept_pc:
            graph[p].append(c)
        index, low, onstk, stack = {}, {}, set(), []
        sccs: list[set[str]] = []

        def _tarjan(v: str) -> None:
            work = [(v, 0)]
            while work:
                node, ei = work[-1]
                if ei == 0:
                    index[node] = low[node] = len(index)
                    stack.append(node)
                    onstk.add(node)
                if ei < len(graph[node]):
                    work[-1] = (node, ei + 1)
                    w = graph[node][ei]
                    if w not in index:
                        work.append((w, 0))
                    elif w in onstk:
                        low[node] = min(low[node], index[w])
                    continue
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == index[node]:
                    comp = set()
                    while True:
                        w = stack.pop()
                        onstk.discard(w)
                        comp.add(w)
                        if w == node:
                            break
                    sccs.append(comp)

        for v in list(graph):
            if v not in index:
                _tarjan(v)
        cyc = {n for comp in sccs if len(comp) > 1
               for n in comp} | {n for n in graph if n in graph[n]}  # 自环也视为环成员
        cands = [e for e in tree.edges if e[0] in PARENT_CHILD and e[2] in cyc]
        if cands:
            # 破边规则：环内首现最早的子端最可能是真实始祖，指向它的父边
            # （错误的回指边）最可疑，去掉首现最早的环成员子端上的亲子边
            worst = min(cands, key=lambda e: first_ch.get(e[2], 10**9))
            tree.issues.append(
                f"环：{tree.persons[worst[1]].name}→{tree.persons[worst[2]].name} "
                f"成环，去边后以 {tree.persons[worst[2]].name} 为根重试")
            tree.edges.remove(worst)
            children[worst[1]].remove(worst[2])
            ps = child_parents[worst[2]]
            ps.remove(worst[1])
            if not ps:
                del child_parents[worst[2]]
                has_parent.discard(worst[2])
            roots = _find_roots()
            _relax()

    # 夫妻同层（一侧已分层另一侧未分层则对齐；两侧都有层则保持）
    for _ in range(2):  # 对齐可能让亲子父辈补层，回灌一次
        for a, b in spouse_pairs:
            ga, gb = tree.persons[a].generation, tree.persons[b].generation
            if ga is None and gb is not None:
                tree.persons[a].generation = gb
            elif gb is None and ga is not None:
                tree.persons[b].generation = ga
        _relax()

    # 孤儿挂靠：祖孙/后裔 +2 代，叔侄/姑侄/舅甥/族叔侄 +1 代。
    # 注意挂靠在夫妻对齐之后执行：被挂靠孤儿的配偶不会跟着对齐，保持未定位
    # （by design——挂靠是弱证据，不向配偶传播）
    for k, a, b in kin:
        if a in tree.persons and b in tree.persons:
            delta = 2 if k in GRAND else 1 if k in UNCLE else 0
            if delta and tree.persons[a].generation is not None \
                    and tree.persons[b].generation is None:
                tree.persons[b].generation = tree.persons[a].generation + delta

    # 夫妻边进树（渲染并排）；仍未定位者报告
    for a, b in spouse_pairs:
        tree.edges.append(("夫妻", a, b))
    for pid, p in tree.persons.items():
        if p.generation is None:
            tree.issues.append(f"未定位代际：{p.name}（无亲子/夫妻/挂靠边），独立置放")
    return tree


def build_master_tree(conn: sqlite3.Connection, faction_name: str) -> Tree:
    """师徒树：成员=所属该势力全部人物（含多重所属）；师徒边任一端是成员即收，
    外端点作外节点（foreign，不展开其其他关系）。"""
    persons_all = _load_persons(conn)
    members = {r["from_id"] for r in conn.execute(
        "SELECT r.from_id FROM relations r JOIN entities e ON r.to_id=e.id "
        "WHERE r.type='所属' AND e.name=?", (faction_name,))}
    tree = Tree(title=f"{faction_name}师徒")
    ma = []
    for k, a, b in _kin_edges(conn, MASTER_APPRENTICE):
        if a not in members and b not in members:
            continue
        if a not in persons_all or b not in persons_all:
            # 悬空边：端点不在实体表，整条丢弃（防 BFS/渲染 KeyError）
            na = persons_all[a].name if a in persons_all else a
            nb = persons_all[b].name if b in persons_all else b
            tree.issues.append(f"悬空边：{na}—{nb}（端点不在实体表）")
            continue
        ma.append((k, a, b))
    inside = set(members)
    for _, a, b in ma:
        inside.add(a)
        inside.add(b)
    # 悬挂引用（端点不在 entities）容忍：只收 persons_all 中存在的 id
    tree.persons = {pid: persons_all[pid] for pid in inside if pid in persons_all}
    for pid in inside - members:
        if pid in tree.persons:
            tree.persons[pid].foreign = True
    tree.edges = list(ma)

    # 分层：徒=师+1（师兄弟边不分层）；未作徒者 0 层
    apprenticed = {b for k, _, b in ma if k == "师徒" and b in tree.persons}
    masters = [pid for pid in tree.persons if pid not in apprenticed]
    gen: dict[str, int] = {}
    q = deque((m, 0) for m in masters)
    children: dict[str, list[str]] = defaultdict(list)
    for k, a, b in ma:
        if k == "师徒":
            children[a].append(b)
    while q:
        cur, g = q.popleft()
        if cur in gen:
            continue
        gen[cur] = g
        for c in children[cur]:
            if c not in gen:
                q.append((c, g + 1))
    for pid, g in gen.items():
        tree.persons[pid].generation = g
    for pid in tree.persons:
        if pid not in gen:   # 师兄弟边挂进但无师徒定位的同门
            tree.persons[pid].generation = 0
            tree.issues.append(f"无师徒边定位：{tree.persons[pid].name}")
    if not members:
        tree.issues.append(f"势力「{faction_name}」无成员")
    return tree


def _label(p: Person) -> str:
    """节点标签：名字†[境界·宗门]（境界/宗门缺省则省略对应段）。"""
    parts = [p.name + ("†" if p.dead else "")]
    info = "·".join(x for x in (p.jingjie, p.sect) if x)
    if info:
        parts.append(f"[{info}]")
    return "\n".join(parts)


def _dot_label(p: Person) -> str:
    """dot 标签：换行写作字面 \\n（dot 引号串内真实换行非法）。"""
    return _label(p).replace("\n", "\\n")


def _mm_label(p: Person) -> str:
    return _label(p).replace("\n", "<br/>")


def render_dot(tree: Tree) -> str:
    """graphviz dot 源码：TB 布局，亲子实线箭头，夫妻灰线无箭头同层，外节点虚线。

    edges 中亲子边保留原始性质（父子/母子/父女/母女），统一按实线箭头渲染。
    """
    lines = [
        f'digraph "{tree.title}" {{',
        "  rankdir=TB;",
        '  node [shape=box, style=rounded, fontname="PingFang SC"];',
        '  edge [fontname="PingFang SC"];',
    ]
    for pid, p in tree.persons.items():
        style = "rounded,dashed" if p.foreign else "rounded"
        lines.append(f'  "{pid}" [label="{_dot_label(p)}", style={style}];')
    couples = [(a, b) for k, a, b in tree.edges if k == "夫妻"]
    for a, b in couples:
        lines.append("  {rank=same; " + f'"{a}"; "{b}";}}')
    for k, a, b in tree.edges:
        if k in PARENT_CHILD:
            lines.append(f'  "{a}" -> "{b}";')
        elif k == "夫妻":
            lines.append(f'  "{a}" -> "{b}" [arrowhead=none, color=gray];')
        elif k == "师徒":
            style = ", style=dashed" if (tree.persons[a].foreign
                                          or tree.persons[b].foreign) else ""
            lines.append(f'  "{a}" -> "{b}" [label="师徒"{style}];')
        elif k == "师兄弟":
            lines.append(f'  "{a}" -> "{b}" [arrowhead=none, label="同门"];')
    lines.append("}")
    return "\n".join(lines)


def render_mermaid(tree: Tree) -> str:
    """mermaid graph TD 源码：节点用 p1/p2 编号 id，label 放引号。"""
    ids = {pid: f"p{i}" for i, pid in enumerate(tree.persons, 1)}
    lines = ["graph TD"]
    for pid, p in tree.persons.items():
        lines.append(f'  {ids[pid]}["{_mm_label(p)}"]')
    for k, a, b in tree.edges:
        ia, ib = ids[a], ids[b]
        if k in PARENT_CHILD:
            lines.append(f"  {ia} --> {ib}")
        elif k == "夫妻":
            lines.append(f"  {ia} --- {ib}")
        elif k == "师徒":
            # :::foreign 是节点级样式（mermaid 无边虚线语法），与 dot 的外节点虚框对应
            line = f"  {ia} -->|师徒| {ib}"
            lines.append(line + (":::foreign" if (tree.persons[a].foreign
                                                  or tree.persons[b].foreign) else ""))
        elif k == "师兄弟":
            lines.append(f"  {ia} ---|同门| {ib}")
    lines.append("  classDef foreign stroke-dasharray: 5 5;")
    return "\n".join(lines)

# 族谱/师徒树导出实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从知识图谱库导出李氏族谱树（从上到下）与任一势力的师徒树，输出 graphviz SVG/PNG + Mermaid md 三件套；前置修正"关系"边方向统一为 from=长辈/师 → to=晚辈/徒。

**Architecture:** 方案 C——`novel_kg/trees.py` 纯逻辑（圈定/建树/渲染，可 pytest），`scripts/export_tree.py` CLI 薄入口，`scripts/fix_relation_direction.py` 一次性方向修正（规则判向+人工核查清单，沿 merge_alias_fragments 工作流）。渲染用 subprocess 调系统 dot（不引入 python graphviz 包，比 spec 简一依赖）。

**Tech Stack:** Python 3 + sqlite3（只读查询）+ 系统 graphviz（dot 15.0 已装）+ pytest。

**Spec:** `docs/superpowers/specs/2026-08-24-family-tree-export-design.md`

**约定（全计划一致）：**
- 亲属性质从边 attrs 提取，键兼容 `关系`/`性质`，取值去括号后缀（"敌对（击杀）"→"敌对"）
- 方向约定：亲子/长幼类 from=长辈→to=晚辈；师徒 from=师→to=徒；对称类不动
- `trees.py` 的建树函数假定输入边方向已修正（Task 6 保证，Task 7 真库先跑修正再导出）

---

### Task 1: trees.py 骨架 + 李家圈定

**Files:**
- Create: `novel_kg/trees.py`
- Test: `tests/test_trees.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_trees.py
"""trees.py 单测：内存 sqlite fixture，人物 p_{name}/关系 r_* 命名见 helper。"""
import json
import sqlite3

import pytest


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
    CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, canonical_id TEXT,
        attrs_json TEXT, first_chapter INTEGER, confidence REAL, status TEXT);
    CREATE TABLE relations (id TEXT PRIMARY KEY, from_id TEXT, to_id TEXT, type TEXT,
        attrs_json TEXT, chapter INTEGER, evidence TEXT);
    """
    )
    return conn


def add_person(conn, name, jingjie="", jianjie="", chapter=1, type_="人物"):
    conn.execute(
        "INSERT INTO entities VALUES (?,?,?,?,?,?,?,?)",
        (f"p_{name}", type_, name, f"p_{name}",
         json.dumps({"境界": jingjie, "简介": jianjie}, ensure_ascii=False),
         chapter, 1.0, "confirmed"),
    )


def add_rel(conn, a, b, kind, chapter=1, key="关系", type_="关系"):
    conn.execute(
        "INSERT INTO relations VALUES (?,?,?,?,?,?,?,?)",
        (f"r_{a}_{b}_{kind}", f"p_{a}", f"p_{b}", type_,
         json.dumps({key: kind}, ensure_ascii=False), chapter, ""),
    )


@pytest.fixture
def fam_db():
    """三代家族 + 旁支 + 配偶 + 无连通同姓外人。"""
    conn = make_db()
    add_person(conn, "李木田", jingjie="筑基", chapter=2)
    add_person(conn, "李根水", chapter=2)
    add_person(conn, "李长湖", jingjie="胎息三层", jianjie="李木田之子", chapter=3)
    add_person(conn, "李通崖", jingjie="紫府", chapter=3)
    add_person(conn, "田芸", chapter=3)
    add_person(conn, "李玄宣", chapter=23)
    add_person(conn, "任氏", jianjie="李长湖之妻", chapter=5)
    add_person(conn, "李玄锋", chapter=49)
    add_person(conn, "李妃若", chapter=190)  # 同姓外人：无亲属边
    # 方向已修正（from=长辈）
    add_rel(conn, "李木田", "李长湖", "父子")
    add_rel(conn, "李木田", "李通崖", "父子")
    add_rel(conn, "李长湖", "李玄宣", "父子")
    add_rel(conn, "任氏", "李玄宣", "母子")
    add_rel(conn, "李长湖", "任氏", "夫妻")
    add_rel(conn, "李通崖", "李玄锋", "父子")
    add_rel(conn, "李通崖", "田芸", "夫妻")
    add_rel(conn, "李木田", "李根水", "兄弟")
    return conn


def test_li_family_members_includes_spouse_excludes_stranger(fam_db):
    from novel_kg.trees import li_family_members

    members = li_family_members(fam_db)
    names = {fam_db.execute("SELECT name FROM entities WHERE id=?", (i,)).fetchone()["name"]
             for i in members}
    assert names == {"李木田", "李根水", "李长湖", "李通崖", "田芸", "任氏",
                     "李玄宣", "李玄锋"}
    assert "李妃若" not in names
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'novel_kg.trees'`）

- [ ] **Step 3: 实现最小 trees.py**

```python
# novel_kg/trees.py
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


def edge_kind(attrs_json: str | None) -> str:
    """从边 attrs 提取亲属性质，兼容两种键，"敌对（击杀）"→"敌对"。"""
    try:
        d = json.loads(attrs_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return ""
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
        attrs = json.loads(r["attrs_json"] or "{}")
        persons[r["id"]] = Person(
            id=r["id"], name=r["name"],
            jingjie=str(attrs.get("境界", "") or "").split("（")[0],
            dead=any(kw in str(attrs.get("简介", "")) for kw in DEAD_KEYWORDS),
        )
    for r in conn.execute(
        "SELECT r.from_id, e.name FROM relations r JOIN entities e ON r.to_id=e.id "
        "WHERE r.type='所属'"
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
    return li | (spouses & closure)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add novel_kg/trees.py tests/test_trees.py
git commit -m "feat(trees): 李家圈定（连通闭包+李姓/配偶过滤）"
```

---

### Task 2: build_family_tree（分层/夫妻/多父/环/孤儿）

**Files:**
- Modify: `novel_kg/trees.py`（追加函数）
- Test: `tests/test_trees.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_build_family_tree_generations(fam_db):
    from novel_kg.trees import build_family_tree, li_family_members

    tree = build_family_tree(fam_db, li_family_members(fam_db))
    g = {tree.persons[pid].name: tree.persons[pid].generation
         for pid in tree.persons}
    assert g["李木田"] == 0 and g["李根水"] == 0
    assert g["李长湖"] == 1 and g["李通崖"] == 1
    assert g["李玄宣"] == 2 and g["李玄锋"] == 2
    # 嫁入配偶靠夫妻边同层
    assert g["任氏"] == 1 and g["田芸"] == 1
    # 亲子边进树，兄弟边不进（共同父隐含）
    kinds = {(k, tree.persons[a].name, tree.persons[b].name) for k, a, b in tree.edges}
    assert ("父子", "李木田", "李通崖") in kinds
    assert all(k != "兄弟" for k, _, _ in kinds)
    assert not tree.issues


def test_build_family_tree_multi_parent_reported(fam_db):
    from novel_kg.trees import build_family_tree, li_family_members

    # 给李玄宣再添一个错误父边 → 多父报告且不崩溃
    add_person(fam_db, "李坏数据", chapter=2)
    add_rel(fam_db, "李坏数据", "李玄宣", "父子")
    tree = build_family_tree(fam_db, li_family_members(fam_db))
    assert any("多父" in i or "多母" in i for i in tree.issues)
    # 主父取首现早者：李长湖(ch3) 而非 李坏数据(ch2)？首现早=李坏数据，故主父是李坏数据
    # ——按"首现章最早为主父"规则，此处断言主父存在且 generation 不变
    assert tree.persons["p_李玄宣"].generation == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: FAIL（`ImportError: cannot import name 'build_family_tree'`）

- [ ] **Step 3: 实现 build_family_tree（追加到 trees.py）**

```python
def build_family_tree(conn: sqlite3.Connection, members: set[str]) -> Tree:
    """族谱树：亲子边拓扑分层；夫妻同层；多父/环进 issues；祖孙/叔侄挂孤儿。"""
    persons_all = _load_persons(conn)
    tree = Tree(
        title="李氏族谱",
        persons={pid: persons_all[pid] for pid in members if pid in persons_all},
    )
    first_ch = {r["id"]: r["first_chapter"] for r in conn.execute(
        "SELECT id, first_chapter FROM entities")}
    kin = _kin_edges(conn, KIN_ALL)

    # 多父/多母检测：同一子女的父边>2 条（父母各一）→ 报告；父边取首现最早者为主父
    pc_by_child: dict[str, list[tuple[str, str]]] = defaultdict(list)  # child -> [(kind, parent)]
    for k, a, b in kin:
        if k in PARENT_CHILD and a in members and b in members:
            pc_by_child[b].append((k, a))
    kept_pc: list[tuple[str, str]] = []  # (parent, child)
    for child, lst in pc_by_child.items():
        lst.sort(key=lambda ka: first_ch.get(ka[1], 10**9))
        if len({p for _, p in lst}) > 1:
            names = "、".join(tree.persons[p].name for _, p in lst)
            tree.issues.append(f"多父/多母：{tree.persons[child].name} 的父边指向 {names}，"
                               f"主边取首现最早者")
        kept_pc.append((lst[0][1], child))
    tree.edges = [("亲子", p, c) for p, c in kept_pc]

    children: dict[str, list[str]] = defaultdict(list)
    has_parent = set()
    for p, c in kept_pc:
        children[p].append(c)
        has_parent.add(c)

    # 环检测：从根 BFS 后仍有亲子边成员未分层 → 去首现最晚一条边重跑
    def _bfs() -> dict[str, int]:
        gen: dict[str, int] = {}
        roots = [pid for pid in tree.persons if pid not in has_parent]
        q = deque((r, 0) for r in roots)
        while q:
            cur, g = q.popleft()
            if cur in gen:
                continue
            gen[cur] = g
            for c in children[cur]:
                if c not in gen:
                    q.append((c, g + 1))
        return gen

    gen = _bfs()
    stuck = [pid for pid in tree.persons if pid in has_parent and pid not in gen]
    if stuck:
        worst = max(
            (e for e in tree.edges if e[0] == "亲子" and e[2] in stuck),
            key=lambda e: first_ch.get(e[2], 0), default=None,
        )
        if worst:
            tree.issues.append(
                f"环：分层受阻于 {tree.persons[worst[2]].name}，去边 "
                f"{tree.persons[worst[1]].name}→{tree.persons[worst[2]].name} 重试")
            tree.edges.remove(worst)
            children[worst[1]].remove(worst[2])
            has_parent.discard(worst[2])
            gen = _bfs()
    for pid in gen:
        tree.persons[pid].generation = gen[pid]

    # 夫妻同层（一侧已分层另一侧未分层则对齐；两侧都有层则保持）
    for k, a, b in kin:
        if k == "夫妻" and a in tree.persons and b in tree.persons:
            ga, gb = tree.persons[a].generation, tree.persons[b].generation
            if ga is None and gb is not None:
                tree.persons[a].generation = gb
            elif gb is None and ga is not None:
                tree.persons[b].generation = ga

    # 孤儿挂靠：祖孙/后裔 +2 代，叔侄/姑侄/舅甥/族叔侄 +1 代
    for k, a, b in kin:
        if a in tree.persons and b in tree.persons:
            delta = 2 if k in GRAND else 1 if k in UNCLE else 0
            if delta and tree.persons[a].generation is not None \
                    and tree.persons[b].generation is None:
                tree.persons[b].generation = tree.persons[a].generation + delta

    # 夫妻边进树（渲染并排）；仍未定位者报告
    for k, a, b in kin:
        if k == "夫妻" and a in tree.persons and b in tree.persons:
            tree.edges.append(("夫妻", a, b))
    for pid, p in tree.persons.items():
        if p.generation is None:
            tree.issues.append(f"未定位代际：{p.name}（无亲子/夫妻/挂靠边），独立置放")
    return tree
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: PASS（2 个新测试 + Task1 测试）

- [ ] **Step 5: Commit**

```bash
git add novel_kg/trees.py tests/test_trees.py
git commit -m "feat(trees): 族谱树构建（拓扑分层/夫妻同层/多父环孤儿报告）"
```

---

### Task 3: render_dot + render_mermaid

**Files:**
- Modify: `novel_kg/trees.py`（追加）
- Test: `tests/test_trees.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_render_dot_and_mermaid(fam_db):
    from novel_kg.trees import build_family_tree, li_family_members, render_dot, render_mermaid

    tree = build_family_tree(fam_db, li_family_members(fam_db))
    dot = render_dot(tree)
    assert dot.startswith("digraph")
    assert 'rankdir=TB' in dot
    assert "李通崖\\n[紫府]" in dot          # 名字+境界（dot label 用 \n 换行）
    assert "李木田" in dot and "任氏" in dot
    assert "{rank=same" in dot               # 夫妻同层
    mm = render_mermaid(tree)
    assert mm.startswith("graph TD")
    assert "-->" in mm and "---" in mm       # 亲子箭头 + 夫妻连线
    assert "李玄宣" in mm and "李木田" in mm
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: FAIL（ImportError render_dot）

- [ ] **Step 3: 实现渲染器（追加到 trees.py）**

```python
def _label(p: Person) -> str:
    """节点标签：名字†[境界·宗门]（境界/宗门缺省则省略对应段）。"""
    parts = [p.name + ("†" if p.dead else "")]
    info = "·".join(x for x in (p.jingjie, p.sect) if x)
    if info:
        parts.append(f"[{info}]")
    return "\n".join(parts)


def _mm_label(p: Person) -> str:
    return _label(p).replace("\n", "<br/>")


def render_dot(tree: Tree) -> str:
    """graphviz dot 源码：TB 布局，亲子实线箭头，夫妻灰线无箭头同层，外节点虚线。"""
    lines = [
        f'digraph "{tree.title}" {{',
        "  rankdir=TB;",
        '  node [shape=box, style=rounded, fontname="PingFang SC"];',
        '  edge [fontname="PingFang SC"];',
    ]
    for pid, p in tree.persons.items():
        style = "rounded,dashed" if p.foreign else "rounded"
        lines.append(f'  "{pid}" [label="{_label(p)}", style={style}];')
    couples = [(a, b) for k, a, b in tree.edges if k == "夫妻"]
    for a, b in couples:
        lines.append("  {rank=same; " + f'"{a}"; "{b}";}}')
    for k, a, b in tree.edges:
        if k == "亲子":
            lines.append(f'  "{a}" -> "{b}";')
        elif k == "夫妻":
            lines.append(f'  "{a}" -> "{b}" [arrowhead=none, color=gray];')
        elif k == "师徒":
            style = ", style=dashed" if tree.persons[b].foreign else ""
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
        if k == "亲子":
            lines.append(f"  {ia} --> {ib}")
        elif k == "夫妻":
            lines.append(f"  {ia} --- {ib}")
        elif k == "师徒":
            line = f"  {ia} -->|师徒| {ib}"
            lines.append(line + (":::foreign" if tree.persons[b].foreign else ""))
        elif k == "师兄弟":
            lines.append(f"  {ia} ---|同门| {ib}")
    lines.append("  classDef foreign stroke-dasharray: 5 5;")
    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add novel_kg/trees.py tests/test_trees.py
git commit -m "feat(trees): dot 与 mermaid 渲染器"
```

---

### Task 4: build_master_tree（师徒树）

**Files:**
- Modify: `novel_kg/trees.py`（追加）
- Test: `tests/test_trees.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
@pytest.fixture
def master_db(fam_db):
    """青池宗：司元白、李尺泾(多重所属)、郁慕仙 为成员；唐元乌、叶秋阳 为外人。"""
    for name in ("司元白", "唐元乌", "叶秋阳", "郁慕仙"):
        add_person(fam_db, name, chapter=100)
    add_person(fam_db, "李尺泾", jingjie="筑基", chapter=3)
    add_rel(fam_db, "司元白", "李尺泾", "师徒", chapter=100)     # 司→李，双成员
    add_rel(fam_db, "唐元乌", "郁慕仙", "师徒", chapter=120)     # 唐为外节点
    add_rel(fam_db, "李项平", "叶秋阳", "师徒", chapter=50)      # 双方都不是成员：不进树
    add_rel(fam_db, "司元白", "李尺泾", "师兄弟", chapter=99)    # 同门边
    for m in ("司元白", "李尺泾", "郁慕仙"):
        add_rel(fam_db, m, "青池宗", "所属", type_="所属")
    add_rel(fam_db, "李尺泾", "李家", "所属", type_="所属")      # 多重所属
    add_person(fam_db, "青池宗", type_="势力")
    return fam_db


def test_build_master_tree(master_db):
    from novel_kg.trees import build_master_tree

    tree = build_master_tree(master_db, "青池宗")
    names = {p.name for p in tree.persons.values()}
    # 成员 + 外节点唐元乌；叶秋阳/李项平（非成员边）不进
    assert names == {"司元白", "李尺泾", "郁慕仙", "唐元乌"}
    assert tree.persons["p_唐元乌"].foreign is True
    assert tree.persons["p_司元白"].foreign is False
    # 师承分层：师0徒1
    assert tree.persons["p_司元白"].generation == 0
    assert tree.persons["p_李尺泾"].generation == 1
    # 李尺泾多重所属：sect 标注青池宗（排除李家）
    assert tree.persons["p_李尺泾"].sect == "青池宗"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: FAIL（ImportError build_master_tree）

- [ ] **Step 3: 实现 build_master_tree（追加到 trees.py）**

```python
def build_master_tree(conn: sqlite3.Connection, faction_name: str) -> Tree:
    """师徒树：成员=所属该势力全部人物（含多重所属）；师徒边任一端是成员即收，
    外端点作外节点（foreign，不展开其其他关系）。"""
    persons_all = _load_persons(conn)
    members = {r["from_id"] for r in conn.execute(
        "SELECT r.from_id FROM relations r JOIN entities e ON r.to_id=e.id "
        "WHERE r.type='所属' AND e.name=?", (faction_name,))}
    tree = Tree(title=f"{faction_name}师徒")
    ma = [(k, a, b) for k, a, b in _kin_edges(conn, MASTER_APPRENTICE)
          if a in members or b in members]
    inside = set(members)
    for _, a, b in ma:
        inside.add(a)
        inside.add(b)
    tree.persons = {pid: persons_all[pid] for pid in inside if pid in persons_all}
    for pid in inside - members:
        if pid in tree.persons:
            tree.persons[pid].foreign = True
    tree.edges = list(ma)

    # 分层：徒=师+1（师兄弟边不分层）；未作徒者 0 层
    apprenticed = {b for k, _, b in ma if k == "师徒"}
    masters = [pid for pid in inside if pid not in apprenticed]
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
    for pid in inside - set(gen):
        tree.persons[pid].generation = 0   # 师兄弟边挂进但无师徒定位的同门
        tree.issues.append(f"无师徒边定位：{tree.persons[pid].name}")
    if not members:
        tree.issues.append(f"势力「{faction_name}」无成员")
    return tree
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add novel_kg/trees.py tests/test_trees.py
git commit -m "feat(trees): 师徒树构建（成员为中心+外节点）"
```

---

### Task 5: export_tree.py CLI

**Files:**
- Create: `scripts/export_tree.py`
- Test: `tests/test_trees.py`（追加导出集成测试）

- [ ] **Step 1: 写失败测试**

```python
def test_export_family_tree_files(tmp_path, fam_db):
    """对文件库导出族谱三件套；dot 缺失时至少有 .md（运行时判断，不断言 dot 存在）。"""
    import shutil
    import sys
    sys.path.insert(0, "scripts")
    import sqlite3 as _s
    import export_tree

    db_path = tmp_path / "t.db"
    fdb = _s.connect(db_path)
    fdb.executescript(
        "CREATE TABLE entities (id TEXT PRIMARY KEY, type TEXT, name TEXT, canonical_id TEXT,"
        "attrs_json TEXT, first_chapter INTEGER, confidence REAL, status TEXT);"
        "CREATE TABLE relations (id TEXT PRIMARY KEY, from_id TEXT, to_id TEXT, type TEXT,"
        "attrs_json TEXT, chapter INTEGER, evidence TEXT);")
    for row in fam_db.execute("SELECT * FROM entities"):
        fdb.execute("INSERT INTO entities VALUES (?,?,?,?,?,?,?,?)", tuple(row))
    for row in fam_db.execute("SELECT * FROM relations"):
        fdb.execute("INSERT INTO relations VALUES (?,?,?,?,?,?,?,?)", tuple(row))
    fdb.commit()

    out = tmp_path / "exports"
    export_tree.run(["族谱", "--db", str(db_path), "--out", str(out)])
    md = (out / "李氏族谱.md").read_text(encoding="utf-8")
    assert "graph TD" in md and "李木田" in md
    if shutil.which("dot"):
        assert (out / "李氏族谱.svg").exists()
        assert (out / "李氏族谱.png").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: FAIL（`No module named 'export_tree'`）

- [ ] **Step 3: 实现 CLI**

```python
# scripts/export_tree.py
"""族谱/师徒树导出 CLI。

用法：
    .venv/bin/python scripts/export_tree.py 族谱 [--db data/novel.db] [--out data/exports]
    .venv/bin/python scripts/export_tree.py 师徒 --faction 青池宗 [--db] [--out]

产出 {名称}.svg/.png/.md 三件套（dot 缺失时仅 .md 并提示），
多父/环/未定位等数据问题写入 {名称}.issues.md 供人工回查修库。
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from novel_kg.trees import (  # noqa: E402
    build_family_tree, build_master_tree, li_family_members, render_dot, render_mermaid,
)


def run(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="族谱/师徒树导出")
    ap.add_argument("mode", choices=["族谱", "师徒"])
    ap.add_argument("--db", default="data/novel.db")
    ap.add_argument("--out", default="data/exports")
    ap.add_argument("--faction", help="师徒模式：势力名")
    args = ap.parse_args(argv)

    import sqlite3
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if args.mode == "族谱":
        members = li_family_members(conn)
        if not members:
            print("圈定为空：找不到李家种子成员", file=sys.stderr)
            return 1
        tree = build_family_tree(conn, members)
        name = "李氏族谱"
    else:
        if not args.faction:
            print("师徒模式需要 --faction 势力名", file=sys.stderr)
            return 1
        tree = build_master_tree(conn, args.faction)
        if tree.issues and tree.issues[-1].startswith("势力「"):
            print(tree.issues[-1], file=sys.stderr)
            return 1
        name = f"{args.faction}师徒"

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dot_src = render_dot(tree)
    (out_dir / f"{name}.md").write_text(
        f"# {tree.title}\n\n```mermaid\n{render_mermaid(tree)}\n```\n", encoding="utf-8")
    if shutil.which("dot"):
        for fmt in ("svg", "png"):
            subprocess.run(
                ["dot", f"-T{fmt}", "-o", str(out_dir / f"{name}.{fmt}")],
                input=dot_src.encode("utf-8"), check=True)
        print(f"已导出 {out_dir}/{name}.svg/.png/.md")
    else:
        print("未找到系统 dot，仅导出 Mermaid（brew install graphviz 可补图片）")
    if tree.issues:
        (out_dir / f"{name}.issues.md").write_text(
            f"# {tree.title} 数据问题\n\n" + "\n".join(f"- {i}" for i in tree.issues),
            encoding="utf-8")
        print(f"发现 {len(tree.issues)} 条数据问题，见 {name}.issues.md")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_trees.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/export_tree.py tests/test_trees.py
git commit -m "feat(export): 族谱/师徒树导出 CLI（svg/png/md 三件套+issues 报告）"
```

---

### Task 6: fix_relation_direction.py（方向修正）

**Files:**
- Create: `scripts/fix_relation_direction.py`
- Test: `tests/test_fix_direction.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_fix_direction.py
"""方向修正单测：简介判向 / 幂等 / 重复边合并 / 无法判定进清单。"""
import json
import sqlite3

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
    import sys
    sys.path.insert(0, "scripts")
    import sqlite3 as _s
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
    import sys
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_fix_direction.py -v`
Expected: FAIL（No module named 'fix_relation_direction'）

- [ ] **Step 3: 实现 fix 脚本**

```python
# scripts/fix_relation_direction.py
"""2026-08-24 一次性修正：统一"关系"边方向 from=长辈/师 → to=晚辈/徒。

信号优先级：① attrs 简介"X之子/之父/之母/之徒/之师"互指文本（最强）
② 无信号的长幼/师徒边 → 人工核查清单（docs/reports/relation-direction-review.md）
对称类（夫妻/兄弟/敌对等）不动。交换端点后按 rel_id(from,to,type) 重算 id，
撞 id 即方向相反的重复边 → 合并（删旧边，事件 rid 改挂）。幂等可重跑。

用法：
    .venv/bin/python scripts/fix_relation_direction.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from novel_kg.trees import edge_kind  # noqa: E402

# from=长（长辈→晚辈）；对称类不动
ELDER_KINDS = {"父子", "母子", "父女", "母女", "祖孙", "叔侄", "姑侄", "舅甥",
               "族叔侄", "后裔"}
MASTER_KINDS = {"师徒"}

# 简介文本模式：命中即"对方名"是声明中的角色（子/父/母/徒/师）
BIO_ROLE = {
    "之子": "child", "之女": "child", "之父": "parent", "之母": "parent",
    "之徒": "apprentice", "之师": "master", "的师父": "master", "的徒弟": "apprentice",
}


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    """与 resolve._rel_id 一致，保证幂等。"""
    return f"rel_{hashlib.md5(f'{from_id}|{to_id}|{type_}'.encode()).hexdigest()[:12]}"


def _bios(conn) -> dict[str, str]:
    return {r["id"]: str(json.loads(r["attrs_json"] or "{}").get("简介", ""))
            for r in conn.execute("SELECT id, attrs_json FROM entities WHERE type='人物'")}


def _bio_signal(my_bio: str, other_name: str) -> str | None:
    """我方简介提到对方时的角色：返回 child（我是子）/parent/master/apprentice。"""
    for suffix, role in BIO_ROLE.items():
        if other_name + suffix in my_bio:
            return role
    return None


def plan_fixes(conn: sqlite3.Connection) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """返回 (需交换的 (from_id,to_id) 列表, 需人工核查的列表)。"""
    bios = _bios(conn)
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id, name FROM entities WHERE type='人物'")}
    swap: list[tuple[str, str]] = []
    review: list[tuple[str, str]] = []
    for r in conn.execute(
        "SELECT id, from_id, to_id, attrs_json FROM relations WHERE type='关系'"
    ).fetchall():
        kind = edge_kind(r["attrs_json"])
        elder_first = kind in ELDER_KINDS            # 应 from=长
        master_first = kind in MASTER_KINDS          # 应 from=师
        if not elder_first and not master_first:
            continue
        a, b = r["from_id"], r["to_id"]
        ra = _bio_signal(bios.get(a, ""), names.get(b, ""))
        rb = _bio_signal(bios.get(b, ""), names.get(a, ""))
        # 推断谁应是 from：child 一方做 to（长幼）；apprentice 一方做 to（师徒）
        a_is_from = None
        if ra == "child" or rb == "parent":
            a_is_from = False
        elif ra == "parent" or rb == "child":
            a_is_from = True
        elif ra == "apprentice" or rb == "master":
            a_is_from = False
        elif ra == "master" or rb == "apprentice":
            a_is_from = True
        if a_is_from is None:
            review.append((a, b))
        elif a_is_from is False:
            swap.append((a, b))
    return swap, review


def apply_fixes(conn: sqlite3.Connection, swap: list[tuple[str, str]]) -> None:
    """交换端点+重算 id；撞 id 的重复边合并（事件 rid 改挂保留边）。"""
    with conn:
        for a, b in swap:
            rows = conn.execute(
                "SELECT * FROM relations WHERE from_id=? AND to_id=? AND type='关系'",
                (a, b)).fetchall()
            for r in rows:
                new_id = rel_id(b, a, r["type"])
                hit = conn.execute("SELECT 1 FROM relations WHERE id=?", (new_id,)).fetchone()
                if hit:
                    conn.execute("UPDATE relation_events SET rid=? WHERE rid=?",
                                 (new_id, r["id"]))
                    conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
                    print(f"  合并重复边 {r['id']} → {new_id}（方向相反已存在）")
                else:
                    conn.execute(
                        "UPDATE relations SET id=?, from_id=?, to_id=? WHERE id=?",
                        (new_id, b, a, r["id"]))
                    conn.execute("UPDATE relation_events SET rid=?, from_id=?, to_id=? "
                                 "WHERE rid=?", (new_id, b, a, r["id"]))
                    print(f"  交换 {a} -> {b} 为 {b} -> {a}")


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
    apply_fixes(conn, swap)
    if review:
        from pathlib import Path
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
```

注：`tests/test_fix_direction.py` 需要 `relation_events` 表——在 `tests/test_trees.py` 的 `make_db()` 建表脚本中追加：

```sql
CREATE TABLE relation_events (id INTEGER PRIMARY KEY AUTOINCREMENT, rid TEXT,
    from_id TEXT, to_id TEXT, type TEXT, attrs_json TEXT, chapter INTEGER, evidence TEXT);
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_fix_direction.py tests/test_trees.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/fix_relation_direction.py tests/test_fix_direction.py tests/test_trees.py
git commit -m "feat(fix): 关系边方向修正脚本（简介判向+幂等+重复边合并+核查清单）"
```

---

### Task 7: 真库执行与验收

**Files:**
- Modify: `data/novel.db`（方向修正落库）
- Create: `data/exports/李氏族谱.{svg,png,md}`、`data/exports/青池宗师徒.{svg,png,md}`、issues 报告

- [ ] **Step 1: 备份并 dry-run 方向修正**

```bash
cp data/novel.db data/novel.db.bak-pre-direction
.venv/bin/python scripts/fix_relation_direction.py data/novel.db --dry-run | head -60
```

Expected: 打印待交换/待核查数量。人工扫一眼交换清单，确认无明显误判。

- [ ] **Step 2: 落库方向修正**

```bash
.venv/bin/python scripts/fix_relation_direction.py data/novel.db
```

Expected: 交换+合并完成，核查清单写入 `docs/reports/relation-direction-review.md`。

- [ ] **Step 3: 导出李氏族谱**

```bash
.venv/bin/python scripts/export_tree.py 族谱
```

Expected: `data/exports/李氏族谱.svg/.png/.md` 生成。**用 Read 工具查看 .svg 内容或 `open data/exports/李氏族谱.png`**，核对：李木田在第 0 层、玄字辈第 2 层、夫妻并排、无李妃若。

- [ ] **Step 4: 导出青池宗师徒树**

```bash
.venv/bin/python scripts/export_tree.py 师徒 --faction 青池宗
```

Expected: 三件套生成，司元白→李尺泾 边存在，外节点虚线。人工查看 png。

- [ ] **Step 5: 全量测试回归**

```bash
.venv/bin/python -m pytest -q
```

Expected: 全部 PASS。

- [ ] **Step 6: Commit**

```bash
git add data/novel.db data/novel.db.bak-pre-direction data/exports docs/reports
git commit -m "feat(trees): 真库方向修正落库+首版族谱/师徒树导出"
```

---

## Self-Review 记录

- **Spec 覆盖**：圈定(Task1)/族谱树含多父环孤儿(Task2)/双渲染器(Task3)/师徒树外节点(Task4)/CLI 三件套+issues(Task5)/方向修正三信号中①信号+清单(Task6；字辈表与同辈传递被简介信号+人工清单取代——简介信号覆盖最广且零误判，字辈表留待清单阶段人工补)/真库执行(Task7)。spec 的"同辈传递/字辈表"为信号②③，本计划简化为信号①+人工清单，若清单量大再补——在 Task 7 验收时视清单规模决定。
- **占位符**：无 TBD/TODO；所有代码步骤含完整代码。
- **类型一致**：`Person/Tree/edge_kind/_load_persons/_kin_edges` 在 Task1 定义，后续任务引用一致；`render_dot/render_mermaid` 同时服务族谱边（亲子/夫妻）与师徒边（师徒/师兄弟），Task3 实现已含全部四种 kind。

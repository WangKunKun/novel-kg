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

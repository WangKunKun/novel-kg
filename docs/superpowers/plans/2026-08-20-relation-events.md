# 关系事件流（时变图谱）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 图谱关系从静态快照升级为可回放的时变事件流——支持任意章节时点查询、演变时间线、图谱边演变摘要与报告呈现。

**Architecture:** 双表方案——`relations` 保持"最新状态"语义（结构不变），新增 `relation_events` 事件流表；resolve 写关系时做三态变化检测（无事件→记/相同→跳过/变化→记+刷新），存量 75 章靠重放 raw_json 零成本生成历史事件。

**Tech Stack:** Python 3.11+ / pydantic / sqlite3 / streamlit + pyvis / pytest

**Spec:** `docs/superpowers/specs/2026-08-20-relation-events-design.md`

**测试命令（项目根 novel-kg/ 下执行）:** `.venv/bin/python -m pytest tests/ -v`

---

### Task 1: schema 变更——「敌对」换成「势力关系」

**Files:**
- Modify: `config/novels/xuanjian.yaml`（relation_types 段）
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 末尾追加：

```python
def test_faction_relation_type_replaces_hostile():
    cfg = load_config("config/novels/xuanjian.yaml")
    names = [rt.name for rt in cfg.relation_types]
    assert "势力关系" in names
    assert "敌对" not in names
    fr = next(rt for rt in cfg.relation_types if rt.name == "势力关系")
    assert fr.from_type == "势力" and fr.to_type == "势力"
    assert "attrs" in fr.description  # 性质须写 attrs 的约束要在描述里
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_config.py::test_faction_relation_type_replaces_hostile -v`
Expected: FAIL（"势力关系"不在 names）

- [ ] **Step 3: 改 yaml**

`config/novels/xuanjian.yaml` 的 relation_types 中，把：

```yaml
  - name: 敌对
    from_type: 势力
    to_type: 势力
```

替换为：

```yaml
  - name: 势力关系
    from_type: 势力
    to_type: 势力
    description: 势力间关系，具体性质（结盟/附庸/联姻/敌对/贸易/雇佣/联防/决裂等，用规范短词）写进 attrs；同一对势力的关系随剧情变化时，也要抽取当前最新状态
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add config/novels/xuanjian.yaml tests/test_config.py
git commit -m "feat(schema): 敌对换成泛化势力关系，性质入 attrs"
```

---

### Task 2: store.py——事件表 + 4 个查询方法

**Files:**
- Modify: `novel_kg/store.py`（SCHEMA 追加表与索引；DB 类加方法）
- Test: `tests/test_store.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_store.py` 末尾追加：

```python
def test_relation_events_record_latest_history_and_as_of(tmp_path):
    from novel_kg.store import DB

    db = DB(str(tmp_path / "ev.db"))
    db.record_relation_event("rel_a", "S1", "S2", "势力关系",
                             '{"性质": "附庸"}', 10, "称臣")
    db.record_relation_event("rel_a", "S1", "S2", "势力关系",
                             '{"性质": "敌对"}', 40, "反目")
    db.record_relation_event("rel_b", "S2", "S3", "势力关系",
                             '{"性质": "结盟"}', 20, "会盟")

    # latest：每对取最新
    assert db.latest_relation_event("S1", "S2")["attrs_json"] == '{"性质": "敌对"}'
    assert db.latest_relation_event("S2", "S3")["attrs_json"] == '{"性质": "结盟"}'
    assert db.latest_relation_event("S3", "S1") is None

    # history：按时间正序
    hist = db.relation_history("S1", "S2")
    assert [h["chapter"] for h in hist] == [10, 40]

    # as_of：时间旅行——第 30 章时 S1->S2 还是附庸
    as_of_30 = db.relations_as_of(30)
    pair = [r for r in as_of_30 if r["from_id"] == "S1" and r["to_id"] == "S2"]
    assert pair[0]["attrs_json"] == '{"性质": "附庸"}'
    # 第 50 章时已反目
    as_of_50 = db.relations_as_of(50)
    pair = [r for r in as_of_50 if r["from_id"] == "S1" and r["to_id"] == "S2"]
    assert pair[0]["attrs_json"] == '{"性质": "敌对"}'
    # 第 5 章时还没有任何 S1->S2 关系
    assert not [r for r in db.relations_as_of(5)
                if r["from_id"] == "S1" and r["to_id"] == "S2"]


def test_relation_events_list_by_type_and_max_chapter(tmp_path):
    from novel_kg.store import DB

    db = DB(str(tmp_path / "ev2.db"))
    db.record_relation_event("rel_a", "S1", "S2", "势力关系", '{}', 10, "x")
    db.record_relation_event("rel_b", "P1", "S1", "所属", '{}', 12, "y")

    assert len(db.list_relation_events("势力关系")) == 1
    assert len(db.list_relation_events()) == 2
    assert db.max_relation_chapter() == 12
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_store.py -v -k relation_events`
Expected: FAIL（`DB` 无 `record_relation_event` 属性）

- [ ] **Step 3: 实现**

`novel_kg/store.py` 的 SCHEMA 字符串末尾（`CREATE INDEX IF NOT EXISTS idx_entity_type_name` 之后）追加：

```sql
CREATE TABLE IF NOT EXISTS relation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rid TEXT,
    from_id TEXT,
    to_id TEXT,
    type TEXT,
    attrs_json TEXT,
    chapter INTEGER,
    evidence TEXT
);
CREATE INDEX IF NOT EXISTS idx_rel_events_pair ON relation_events(from_id, to_id, id);
```

DB 类"关系"区块中 `list_relations` 之后追加：

```python
    # ---------- 关系事件流（时变） ----------
    def record_relation_event(self, rid: str, from_id: str, to_id: str, type_: str,
                              attrs_json: str, chapter: int, evidence: str) -> None:
        self.conn.execute(
            "INSERT INTO relation_events(rid,from_id,to_id,type,attrs_json,chapter,evidence) "
            "VALUES(?,?,?,?,?,?,?)",
            (rid, from_id, to_id, type_, attrs_json, chapter, evidence),
        )
        self.conn.commit()

    def latest_relation_event(self, from_id: str, to_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM relation_events WHERE from_id=? AND to_id=? "
            "ORDER BY id DESC LIMIT 1",
            (from_id, to_id),
        ).fetchone()

    def relation_history(self, from_id: str, to_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM relation_events WHERE from_id=? AND to_id=? ORDER BY id",
                (from_id, to_id),
            ).fetchall()
        ]

    def relations_as_of(self, chapter: int) -> list[dict]:
        """第 chapter 章时的关系图：每对取 chapter<=X 的最新事件。"""
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT e.* FROM relation_events e JOIN "
                "(SELECT from_id, to_id, MAX(id) AS max_id FROM relation_events "
                " WHERE chapter<=? GROUP BY from_id, to_id) last "
                "ON e.id = last.max_id",
                (chapter,),
            ).fetchall()
        ]

    def list_relation_events(self, type_: str | None = None) -> list[dict]:
        if type_:
            rows = self.conn.execute(
                "SELECT * FROM relation_events WHERE type=?", (type_,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM relation_events").fetchall()
        return [dict(r) for r in rows]

    def max_relation_chapter(self) -> int:
        row = self.conn.execute(
            "SELECT MAX(chapter) AS m FROM relation_events"
        ).fetchone()
        return row["m"] or 0
```

同时在 `store.py` 文件末尾（`relation_label` 函数旁）追加演变摘要函数（viz 与 report 共用，放 store 避免两处依赖 streamlit 模块）：

```python
def evolution_text(history: list[dict]) -> str:
    """事件流拼成"10章:附庸 → 40章:敌对"式摘要；attrs 值取顿号拼接。"""
    parts = []
    for h in history:
        attrs = json.loads(h.get("attrs_json") or "{}")
        desc = "、".join(str(v) for v in attrs.values() if v)
        parts.append(f"{h['chapter']}章:{desc or h['type']}")
    return " → ".join(parts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add novel_kg/store.py tests/test_store.py
git commit -m "feat(store): relation_events 事件表与 latest/history/as_of 查询"
```

---

### Task 3: resolve.py——三态变化检测

**Files:**
- Modify: `novel_kg/resolve.py`（关系写入路径）
- Test: `tests/test_resolve.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_resolve.py` 末尾追加：

```python
def test_relation_events_three_states(tmp_path):
    """三态：首现记事件；同状态跳过；变化记新事件+刷新当前态。"""
    schema = load_config("config/novels/xuanjian.yaml")
    db = DB(str(tmp_path / "ev.db"))

    def _ext(attrs: dict) -> ChapterExtraction:
        return ChapterExtraction(
            entities=[
                ExtractedEntity(type="势力", name="李家", evidence="李家"),
                ExtractedEntity(type="势力", name="镜铁山", evidence="镜铁山"),
            ],
            relations=[
                ExtractedRelation(from_name="李家", to_name="镜铁山", type="势力关系",
                                  attrs=attrs, evidence="某章原文"),
            ],
        )

    # 状态1：首现 -> 记事件
    resolve_extraction(db, schema, 10, _ext({"性质": "附庸"}))
    assert len(db.list_relation_events()) == 1
    assert db.list_relations()[0]["attrs_json"] == '{"性质": "附庸"}'

    # 状态2：同 (type, attrs) 重复 -> 跳过，不产生新事件
    resolve_extraction(db, schema, 12, _ext({"性质": "附庸"}))
    assert len(db.list_relation_events()) == 1

    # 状态3：attrs 变化 -> 新事件 + relations 刷新（同 rid，chapter 更新）
    resolve_extraction(db, schema, 40, _ext({"性质": "敌对"}))
    events = db.list_relation_events()
    assert len(events) == 2
    rels = db.list_relations()
    assert len(rels) == 1
    assert rels[0]["attrs_json"] == '{"性质": "敌对"}'
    assert rels[0]["chapter"] == 40

    # as_of 语义：30 章时应是附庸
    as_of = [r for r in db.relations_as_of(30)
             if r["from_id"] == rels[0]["from_id"]]
    assert as_of[0]["attrs_json"] == '{"性质": "附庸"}'


def test_relation_type_change_replaces_old_edge(tmp_path):
    """同一对实体关系 type 变化时，relations 旧行被替换（每对至多一条当前边）。"""
    schema = load_config("config/novels/xuanjian.yaml")
    db = DB(str(tmp_path / "ev3.db"))

    ext_a = ChapterExtraction(
        entities=[
            ExtractedEntity(type="人物", name="甲", evidence="x"),
            ExtractedEntity(type="势力", name="李家", evidence="x"),
        ],
        relations=[ExtractedRelation(from_name="甲", to_name="李家", type="所属",
                                     evidence="x")],
    )
    resolve_extraction(db, schema, 5, ext_a)
    assert len(db.list_relations()) == 1

    # 同一对改成"关系"类型（type 变化）：旧行删除，只留新行
    ext_b = ChapterExtraction(
        entities=[],
        relations=[ExtractedRelation(from_name="甲", to_name="李家", type="关系",
                                     attrs={"关系": "供奉"}, evidence="x")],
    )
    resolve_extraction(db, schema, 8, ext_b)
    rels = db.list_relations()
    assert len(rels) == 1
    assert rels[0]["type"] == "关系"
    # 事件流完整保留两段历史
    assert len(db.list_relation_events()) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_resolve.py -v -k events`
Expected: FAIL（`list_relation_events` 不存在——若 Task 2 已完成则失败于事件数为 0，因为 resolve 还没写事件）

- [ ] **Step 3: 实现**

先改 `novel_kg/store.py` 的 `upsert_relation`——语义升级为"最新状态"，ON CONFLICT 要跟最新事件走（更新 chapter/evidence）。将：

```python
    def upsert_relation(self, rid: str, from_id: str, to_id: str, type_: str,
                        attrs_json: str, chapter: int, evidence: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO relations(id,from_id,to_id,type,attrs_json,chapter,evidence) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "attrs_json=excluded.attrs_json, chapter=excluded.chapter, "
            "evidence=excluded.evidence",
            (rid, from_id, to_id, type_, attrs_json, chapter, evidence),
        )
        self.conn.commit()
```

注意原实现是 `INSERT OR IGNORE`——静默忽略冲突，attrs/chapter 不更新，必须改为上面的 `ON CONFLICT(id) DO UPDATE` 写法（否则第 3 态刷新无效）。

再改 `novel_kg/resolve.py`：文件顶部 import 区加 `import json`（已有则跳过）。模块级加：

```python
def _norm_attrs(attrs: dict[str, str]) -> str:
    """attrs 规范化序列化：变化检测的比较基准。"""
    return json.dumps(attrs, sort_keys=True, ensure_ascii=False)
```

`resolve_extraction` 内关系循环，将：

```python
        if from_id and to_id:
            db.upsert_relation(
                _rel_id(from_id, to_id, r.type), from_id, to_id, r.type,
                json.dumps(r.attrs, ensure_ascii=False), chapter_idx, r.evidence,
            )
```

替换为：

```python
        if from_id and to_id:
            rid = _rel_id(from_id, to_id, r.type)
            latest = db.latest_relation_event(from_id, to_id)
            unchanged = (
                latest is not None
                and latest["type"] == r.type
                and latest["attrs_json"] == _norm_attrs(r.attrs)
            )
            if not unchanged:
                attrs_json = json.dumps(r.attrs, ensure_ascii=False)
                # 每对至多一条当前边：type 变化时旧边作废
                db.conn.execute(
                    "DELETE FROM relations WHERE from_id=? AND to_id=? AND id<>?",
                    (from_id, to_id, rid),
                )
                db.record_relation_event(rid, from_id, to_id, r.type,
                                         attrs_json, chapter_idx, r.evidence)
                db.upsert_relation(rid, from_id, to_id, r.type,
                                   attrs_json, chapter_idx, r.evidence)
                db.conn.commit()
```

注意：第 3 态分支里 `record_relation_event` 与 `upsert_relation` 内部各自 commit，DELETE 依赖其后 commit 生效，无需额外事务处理。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 全 PASS（含既有 `test_resolve_creates_entities_merges_aliases_and_links_relations` 的幂等断言——同状态跳过不破坏它）

- [ ] **Step 5: Commit**

```bash
git add novel_kg/resolve.py novel_kg/store.py tests/test_resolve.py
git commit -m "feat(resolve): 关系写入三态变化检测，事件流+当前态同步"
```

---

### Task 4: viz_app.py——时间滑块 + 演变摘要 + 演变面板 + 补颜色

**Files:**
- Modify: `novel_kg/viz_app.py`
- Test: `tests/test_viz_app.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_viz_app.py` 末尾追加：

```python
def test_load_graph_as_of_uses_event_state(tmp_path):
    from novel_kg.store import DB
    from novel_kg.viz_app import load_graph

    db = DB(str(tmp_path / "g.db"))
    for e in [{"id": "S1", "type": "势力", "name": "李家"},
              {"id": "S2", "type": "势力", "name": "镜铁山"}]:
        db.upsert_entity(e["id"], e["type"], e["name"], e["id"], "{}", 1, 0.9, "confirmed")
    db.record_relation_event("rel_a", "S1", "S2", "势力关系",
                             '{"性质": "附庸"}', 10, "称臣")
    db.record_relation_event("rel_a", "S1", "S2", "势力关系",
                             '{"性质": "敌对"}', 40, "反目")
    # relations 表 = 最新状态（resolve 三态负责同步，这里手动模拟）
    db.upsert_relation("rel_a", "S1", "S2", "势力关系",
                       '{"性质": "敌对"}', 40, "反目")

    _, rels_30 = load_graph(db, as_of=30)
    assert rels_30[0]["attrs_json"] == '{"性质": "附庸"}'
    _, rels_now = load_graph(db)  # 不传 as_of -> 最新（relations 表）
    assert rels_now[0]["attrs_json"] == '{"性质": "敌对"}'


def test_evolution_text_formats_chapters():
    from novel_kg.store import evolution_text

    hist = [
        {"chapter": 10, "attrs_json": '{"性质": "附庸"}'},
        {"chapter": 40, "attrs_json": '{"性质": "敌对"}'},
    ]
    assert evolution_text(hist) == "10章:附庸 → 40章:敌对"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_viz_app.py -v`
Expected: FAIL（load_graph 无 as_of 参数 / evolution_text 不存在）

- [ ] **Step 3: 实现**

`novel_kg/viz_app.py`：

顶部 import 改为：

```python
import streamlit as st
from pyvis.network import Network

from novel_kg.store import DB, evolution_text, relation_label
```

（`evolution_text` 已在 Task 2 定义于 `store.py`，此处只 import；`json` 也无需引入——attrs 解析已封装在 `evolution_text` 里。）

`load_graph` 加 as_of 参数：

```python
def load_graph(db: DB, entity_type: str | None = None,
               rel_type: str | None = None,
               as_of: int | None = None) -> tuple[list[dict], list[dict]]:
    """从 DB 读实体与关系，可按类型过滤。as_of=第X章时用事件流的当时状态。"""
    entities = db.list_entities(entity_type)
    ent_ids = {e["id"] for e in entities}
    rels = db.relations_as_of(as_of) if as_of else db.list_relations()
    rels = [r for r in rels
            if r["from_id"] in ent_ids and r["to_id"] in ent_ids
            and (rel_type is None or r["type"] == rel_type)]
    return entities, rels
```

`render_network` 加边演变 title 支持——签名改为：

```python
def render_network(entities: list[dict], rels: list[dict],
                   evolution: dict[str, str] | None = None) -> Network:
```

（`evolution` 键为 `f"{from_id}->{to_id}"`。）边循环改为：

```python
    for r in rels:
        key = f"{r['from_id']}->{r['to_id']}"
        evo = (evolution or {}).get(key)
        title = r.get("evidence", "")
        if evo:
            title = f"演变：{evo}\n证据：{title}"
        net.add_edge(r["from_id"], r["to_id"], label=relation_label(r), title=title)
```

`type_colors` 补两个键（仙基四拆遗留）：

```python
    type_colors = {"人物": "#e6194b", "势力": "#3cb44b", "仙基": "#4363d8",
                   "道具": "#f58231", "功法": "#911eb4", "术法": "#46f0f0"}
```

`main()` 改造——侧栏滑块 + 演变面板。将 `main` 中 `et = ...` 之后到 `st.components.v1.html(...)` 的整块替换为：

```python
    et = None if sel_type == "（全部）" else sel_type
    rt = None if sel_rel == "（全部）" else sel_rel

    max_ch = db.max_relation_chapter()
    as_of = None
    if max_ch:
        pick = st.sidebar.slider("截至章节（拖动回看当时关系）", 1, max_ch, max_ch)
        as_of = pick if pick < max_ch else None  # 拉满即最新

    entities, rels = load_graph(db, et, rt, as_of=as_of)
    st.write(f"实体 {len(entities)} 条，关系 {len(rels)} 条"
             + (f"（截至第 {as_of} 章）" if as_of else ""))

    if entities:
        evolution = {}
        for r in rels:
            hist = db.relation_history(r["from_id"], r["to_id"])
            if len(hist) > 1:
                evolution[f"{r['from_id']}->{r['to_id']}"] = evolution_text(hist)
        net = render_network(entities, rels, evolution)
        net.save_graph("/tmp/novel_kg_graph.html")
        st.components.v1.html(open("/tmp/novel_kg_graph.html", encoding="utf-8").read(),
                              height=620, scrolling=True)

    # 关系演变面板
    st.subheader("📖 关系演变时间线")
    ent_names = sorted(e["name"] for e in db.list_entities())
    c1, c2 = st.columns(2)
    a = c1.selectbox("实体甲", ent_names)
    b = c2.selectbox("实体乙", ent_names)
    if a and b and a != b:
        ea = db.find_entity_id_any(a)
        eb = db.find_entity_id_any(b)
        rows = []
        if ea and eb:
            rows = sorted(db.relation_history(ea, eb) + db.relation_history(eb, ea),
                          key=lambda h: h["chapter"])
        if rows:
            st.dataframe([{"章": h["chapter"], "类型": h["type"],
                           "attrs": h["attrs_json"], "证据": h["evidence"]}
                          for h in rows])
        else:
            st.write("（这对实体没有已记录的关系事件）")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 全 PASS

- [ ] **Step 5: 冒烟 streamlit（可选但推荐）**

Run: `.venv/bin/streamlit run novel_kg/viz_app.py --server.headless true &` 打开 http://localhost:8501 确认滑块/面板渲染后 Ctrl-C。
Expected: 页面正常，无 traceback

- [ ] **Step 6: Commit**

```bash
git add novel_kg/viz_app.py tests/test_viz_app.py
git commit -m "feat(viz): 截至章节滑块、边演变悬停、关系时间线面板、补功法/术法颜色"
```

---

### Task 5: report.py——势力关系演变成节

**Files:**
- Modify: `novel_kg/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_report.py` 末尾追加（测试自包含，不依赖该文件其他 fixture）：

```python
def test_report_has_faction_evolution_section(tmp_path):
    from novel_kg.report import generate_report
    from novel_kg.store import DB

    db = DB(str(tmp_path / "r.db"))
    for e in [{"id": "S1", "type": "势力", "name": "李家"},
              {"id": "S2", "type": "势力", "name": "镜铁山"}]:
        db.upsert_entity(e["id"], e["type"], e["name"], e["id"], "{}", 1, 0.9, "confirmed")
    db.record_relation_event("rel_a", "S1", "S2", "势力关系",
                             '{"性质": "附庸"}', 10, "称臣纳贡")
    db.record_relation_event("rel_a", "S1", "S2", "势力关系",
                             '{"性质": "敌对"}', 40, "反目攻伐")

    report = generate_report(db)
    assert "## 势力关系演变" in report
    assert "李家 → 镜铁山" in report
    assert "10章" in report and "40章" in report
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_report.py -v -k faction`
Expected: FAIL（报告无该节）

- [ ] **Step 3: 实现**

`novel_kg/report.py` 顶部 import 区改为：

```python
import json

from novel_kg.store import DB, evolution_text, relation_label
```

（`evolution_text` 已在 Task 2 定义于 `store.py`。）

`generate_report` 的"# 关系"节之前插入：

```python
    # 势力关系演变（事件流时间线）
    lines.append("## 势力关系演变")
    name_by_id0 = {e["id"]: e["name"] for e in db.list_entities()}
    faction_events = db.list_relation_events("势力关系")
    if faction_events:
        pairs: dict[tuple[str, str], list[dict]] = {}
        for ev in faction_events:
            pairs.setdefault((ev["from_id"], ev["to_id"]), []).append(ev)
        for (fid, tid), evs in pairs.items():
            a = name_by_id0.get(fid, "?")
            b = name_by_id0.get(tid, "?")
            lines.append(f"### {a} → {b}")
            lines.append(f"- 演变：{evolution_text(evs)}")
            for ev in evs:
                lines.append(f"  - 第{ev['chapter']}章：{ev['evidence'] or '（无证据）'}")
    else:
        lines.append("- （暂无势力关系事件）")
    lines.append("")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add novel_kg/report.py tests/test_report.py
git commit -m "feat(report): 势力关系演变成节"
```

---

### Task 6: 存量迁移脚本——敌对→势力关系 + raw_json 同步

**Files:**
- Create: `scripts/migrate_relation_events.py`

- [ ] **Step 1: 写脚本**

```python
"""2026-08-20 一次性迁移：「敌对」→「势力关系」（attrs 补性质），raw_json 同步。

幂等：跑过一次后 WHERE type='敌对' 查不到即空转。
用法：
    .venv/bin/python scripts/migrate_relation_events.py data/novel.db [--dry-run]
"""
import hashlib
import json
import sqlite3
import sys


def rel_id(from_id: str, to_id: str, type_: str) -> str:
    """与 resolve._rel_id 一致（md5 前 12 位），保证重放幂等。"""
    key = f"{from_id}|{to_id}|{type_}"
    return f"rel_{hashlib.md5(key.encode()).hexdigest()[:12]}"


def main() -> None:
    db_path = sys.argv[1] if len(sys.argv) > 1 else "data/novel.db"
    dry = "--dry-run" in sys.argv
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("SELECT * FROM relations WHERE type='敌对'").fetchall()
    print(f"敌对关系 {len(rows)} 条待迁移")
    if dry:
        for r in rows:
            print(f"  {r['from_id']} -敌对-> {r['to_id']} 将改为 势力关系(性质:敌对)")
        print("dry-run，不落库")
        return

    with conn:
        for r in rows:
            # attrs 合并补性质（保留既有键）
            attrs = json.loads(r["attrs_json"] or "{}")
            attrs.setdefault("性质", "敌对")
            attrs_json = json.dumps(attrs, ensure_ascii=False)
            new_id = rel_id(r["from_id"], r["to_id"], "势力关系")
            hit = conn.execute("SELECT 1 FROM relations WHERE id=?", (new_id,)).fetchone()
            if hit:
                conn.execute("DELETE FROM relations WHERE id=?", (r["id"],))
            else:
                conn.execute(
                    "UPDATE relations SET id=?, type=?, attrs_json=? WHERE id=?",
                    (new_id, "势力关系", attrs_json, r["id"]),
                )
        # raw_json 同步：relations[].type 敌对 -> 势力关系 + attrs 补性质
        for row in conn.execute("SELECT chapter, raw_json FROM extractions").fetchall():
            data = json.loads(row["raw_json"])
            dirty = False
            for r in data.get("relations", []):
                if r.get("type") == "敌对":
                    r["type"] = "势力关系"
                    attrs = r.get("attrs") or {}
                    attrs.setdefault("性质", "敌对")
                    r["attrs"] = attrs
                    dirty = True
            if dirty:
                conn.execute(
                    "UPDATE extractions SET raw_json=? WHERE chapter=?",
                    (json.dumps(data, ensure_ascii=False), row["chapter"]),
                )
    print("落库完成")
    for row in conn.execute(
        "SELECT type, COUNT(*) n FROM relations GROUP BY type ORDER BY n DESC"
    ):
        print(f"  {row['type']}: {row['n']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: dry-run 检查**

Run: `.venv/bin/python scripts/migrate_relation_events.py data/novel.db --dry-run`
Expected: 打印 15 条敌对关系待迁移

- [ ] **Step 3: 真跑 + 幂等验证**

Run: `.venv/bin/python scripts/migrate_relation_events.py data/novel.db && .venv/bin/python scripts/migrate_relation_events.py data/novel.db --dry-run`
Expected: 第一次落库后统计出现 `势力关系: 15`；第二次 dry-run 显示 0 条待迁移（幂等）

- [ ] **Step 4: Commit**

```bash
git add scripts/migrate_relation_events.py
git commit -m "feat(migrate): 敌对存量迁移势力关系脚本（幂等）"
```

---

### Task 7: 重放生成历史事件 + 验证

**Files:** 无代码改动（验证任务）

- [ ] **Step 1: 备份库**

```bash
cp data/novel.db data/novel.db.bak-rel-events
```

- [ ] **Step 2: 重放 75 章（extraction 已缓存，不调 LLM）**

Run: `.venv/bin/python -m novel_kg.cli --novel ../玄鉴仙族.txt --schema config/novels/xuanjian.yaml --db data/novel.db --limit 75`
Expected: 秒级到分钟级完成（无 LLM 调用），打印实体/关系统计

- [ ] **Step 3: 验证事件质量**

```bash
sqlite3 data/novel.db "
SELECT '事件/关系比:', (SELECT COUNT(*) FROM relation_events)||'/'||(SELECT COUNT(*) FROM relations);
SELECT '多事件对 top10:';
SELECT ef.name, et.name, COUNT(*) n FROM relation_events e
JOIN entities ef ON ef.id=e.from_id JOIN entities et ON et.id=e.to_id
GROUP BY e.from_id, e.to_id ORDER BY n DESC LIMIT 10;"
```

Expected: 事件/关系比 ≤ 3x；top 列表里能识别出有剧情变化的势力对或人物对；抽查多事件对的各事件 attrs 是否真实演变（若全是措辞漂移的假事件——如同义 attrs 反复出现——报告用户并收紧比较规则再重放）

- [ ] **Step 4: 幂等验证**

再跑一次 Step 2 的命令。
Expected: 实体/关系/事件数完全不变

- [ ] **Step 5: 全量测试收尾**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: 全 PASS

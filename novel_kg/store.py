import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS chapters (
    id INTEGER PRIMARY KEY,
    title TEXT,
    text TEXT
);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT,
    name TEXT,
    canonical_id TEXT,
    attrs_json TEXT,
    first_chapter INTEGER,
    confidence REAL,
    status TEXT
);
CREATE TABLE IF NOT EXISTS aliases (
    entity_id TEXT,
    alias TEXT,
    UNIQUE(entity_id, alias)
);
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    from_id TEXT,
    to_id TEXT,
    type TEXT,
    attrs_json TEXT,
    chapter INTEGER,
    evidence TEXT
);
CREATE TABLE IF NOT EXISTS classifications (
    entity_id TEXT,
    dimension TEXT,
    value TEXT,
    UNIQUE(entity_id, dimension, value)
);
CREATE TABLE IF NOT EXISTS taxonomy (
    dimension TEXT,
    value TEXT,
    parent_value TEXT
);
CREATE TABLE IF NOT EXISTS extractions (
    chapter INTEGER PRIMARY KEY,
    raw_json TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_alias ON aliases(alias);
CREATE INDEX IF NOT EXISTS idx_entity_type_name ON entities(type, name);
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
"""


class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # ---------- 章节 ----------
    def upsert_chapter(self, idx: int, title: str, text: str) -> None:
        self.conn.execute(
            "INSERT INTO chapters(id,title,text) VALUES(?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, text=excluded.text",
            (idx, title, text),
        )
        self.conn.commit()

    def get_chapter(self, idx: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM chapters WHERE id=?", (idx,)).fetchone()

    # ---------- 原始抽取（断点续传） ----------
    def save_extraction(self, chapter: int, raw_json: str) -> None:
        self.conn.execute(
            "INSERT INTO extractions(chapter,raw_json,created_at) VALUES(?,?,datetime('now')) "
            "ON CONFLICT(chapter) DO UPDATE SET raw_json=excluded.raw_json",
            (chapter, raw_json),
        )
        self.conn.commit()

    def has_extraction(self, chapter: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM extractions WHERE chapter=?", (chapter,)
        ).fetchone()
        return row is not None

    def get_extraction(self, chapter: int) -> str | None:
        row = self.conn.execute(
            "SELECT raw_json FROM extractions WHERE chapter=?", (chapter,)
        ).fetchone()
        return row["raw_json"] if row else None

    # ---------- 实体 ----------
    def upsert_entity(self, eid: str, type_: str, name: str, canonical_id: str,
                      attrs_json: str, first_chapter: int, confidence: float,
                      status: str) -> None:
        self.conn.execute(
            "INSERT INTO entities(id,type,name,canonical_id,attrs_json,first_chapter,confidence,status) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name, attrs_json=excluded.attrs_json, status=excluded.status",
            (eid, type_, name, canonical_id, attrs_json, first_chapter, confidence, status),
        )
        self.conn.commit()

    def add_alias(self, entity_id: str, alias: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO aliases(entity_id,alias) VALUES(?,?)",
            (entity_id, alias),
        )
        self.conn.commit()

    def find_entity_id(self, type_: str, name: str) -> str | None:
        row = self.conn.execute(
            "SELECT e.id FROM entities e WHERE e.type=? AND e.name=?", (type_, name)
        ).fetchone()
        if row:
            return row["id"]
        row = self.conn.execute(
            "SELECT a.entity_id FROM aliases a JOIN entities e ON e.id=a.entity_id "
            "WHERE a.alias=? AND e.type=?",
            (name, type_),
        ).fetchone()
        return row["entity_id"] if row else None

    def find_entity_id_any(self, name: str) -> str | None:
        row = self.conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
        if row:
            return row["id"]
        row = self.conn.execute(
            "SELECT entity_id FROM aliases WHERE alias=?", (name,)
        ).fetchone()
        return row["entity_id"] if row else None

    def add_classification(self, entity_id: str, dimension: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO classifications(entity_id,dimension,value) VALUES(?,?,?)",
            (entity_id, dimension, value),
        )
        self.conn.commit()

    def list_classifications(self, entity_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT dimension,value FROM classifications WHERE entity_id=?", (entity_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 关系 ----------
    def upsert_relation(self, rid: str, from_id: str, to_id: str, type_: str,
                        attrs_json: str, chapter: int, evidence: str) -> None:
        self.conn.execute(
            "INSERT INTO relations(id,from_id,to_id,type,attrs_json,chapter,evidence) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "attrs_json=excluded.attrs_json, chapter=excluded.chapter, "
            "evidence=excluded.evidence",
            (rid, from_id, to_id, type_, attrs_json, chapter, evidence),
        )
        self.conn.commit()

    def list_relations(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM relations").fetchall()]

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

    # ---------- 查询（报告/可视化用） ----------
    def entity_counts(self) -> list[dict]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT type, COUNT(*) AS n FROM entities GROUP BY type ORDER BY n DESC"
            ).fetchall()
        ]

    def list_entities(self, type_: str | None = None) -> list[dict]:
        if type_:
            return [
                dict(r)
                for r in self.conn.execute(
                    "SELECT * FROM entities WHERE type=?", (type_,)
                ).fetchall()
            ]
        return [dict(r) for r in self.conn.execute("SELECT * FROM entities").fetchall()]


def relation_label(rel: dict) -> str:
    """生成关系的可读标签：优先用 attrs 里的具体关系（父子/兄弟/夫妻…），
    没有则回退到 type（所属/持有/修炼/势力关系）。兼容 LLM 偶尔用的英文键。"""
    attrs = json.loads(rel.get("attrs_json") or "{}")
    details = [str(v) for v in attrs.values() if v]
    return "、".join(details) if details else rel["type"]


def evolution_text(history: list[dict]) -> str:
    """事件流拼成"10章:附庸 → 40章:敌对"式摘要；attrs 值取顿号拼接。"""
    parts = []
    for h in history:
        attrs = json.loads(h.get("attrs_json") or "{}")
        desc = "、".join(str(v) for v in attrs.values() if v)
        parts.append(f"{h['chapter']}章:{desc or h['type']}")
    return " → ".join(parts)

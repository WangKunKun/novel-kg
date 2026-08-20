import hashlib
import json
import uuid

from novel_kg.config import SchemaConfig
from novel_kg.models import ChapterExtraction
from novel_kg.store import DB


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _rel_id(from_id: str, to_id: str, type_: str) -> str:
    """确定性关系 id：同样的 (from,to,type) 只产生一行（跨章也不重复），图谱边唯一。
    截断长度必须是 12：存量库即 12 位，改长改短都会导致重放时 id 不一致插重复行。"""
    key = f"{from_id}|{to_id}|{type_}"
    return f"rel_{hashlib.md5(key.encode()).hexdigest()[:12]}"


def resolve_extraction(
    db: DB, schema: SchemaConfig, chapter_idx: int, ext: ChapterExtraction
) -> None:
    """把一章抽取结果并入图谱：按 (类型, 名字/别名) 归并实体，分配稳定 ID，再挂关系。"""

    def get_or_create(type_: str, name: str, aliases: list[str],
                      attrs: dict[str, str], evidence: str) -> str:
        eid = db.find_entity_id(type_, name)
        if eid is None:
            for a in aliases:
                eid = db.find_entity_id(type_, a)
                if eid is not None:
                    break
        if eid is None:
            # 同名但 type 不同：复用已有实体，防止同名双行
            # （库内 type 已人工修正过，优先于 LLM 单章判断）
            for cand in [name, *aliases]:
                eid = db.find_entity_id_any(cand)
                if eid is not None:
                    break
        if eid is None:
            eid = _new_id(type_)
            status = "confirmed" if evidence else "pending_review"
            conf = 0.9 if evidence else 0.5
            db.upsert_entity(
                eid, type_, name, eid,
                json.dumps(attrs, ensure_ascii=False), chapter_idx, conf, status,
            )
        # 累积别名
        db.add_alias(eid, name)
        for a in aliases:
            db.add_alias(eid, a)
        return eid

    # 1) 实体
    name_to_id: dict[tuple[str, str], str] = {}
    for e in ext.entities:
        eid = get_or_create(e.type, e.name, list(e.aliases), e.attrs, e.evidence)
        name_to_id[(e.type, e.name)] = eid
        for a in e.aliases:
            name_to_id[(e.type, a)] = eid
        for dim, val in e.classifications.items():
            db.add_classification(eid, dim, val)

    # 2) 关系（端点按关系声明的类型查，查不到再跨类型兜底）
    for r in ext.relations:
        rt = schema.relation_type(r.type)
        from_type = rt.from_type if rt else None
        to_type = rt.to_type if rt else None
        from_id = (
            (name_to_id.get((from_type, r.from_name)) if from_type else None)
            or db.find_entity_id_any(r.from_name)
        )
        to_id = (
            (name_to_id.get((to_type, r.to_name)) if to_type else None)
            or db.find_entity_id_any(r.to_name)
        )
        if from_id and to_id:
            db.upsert_relation(
                _rel_id(from_id, to_id, r.type), from_id, to_id, r.type,
                json.dumps(r.attrs, ensure_ascii=False), chapter_idx, r.evidence,
            )

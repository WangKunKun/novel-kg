from novel_kg.config import SchemaConfig, load_config
from novel_kg.extract import extract_chapter
from novel_kg.ingest import read_novel
from novel_kg.llm_client import LLMClient
from novel_kg.models import ChapterExtraction
from novel_kg.resolve import resolve_extraction
from novel_kg.store import DB


def run_pipeline(
    novel_path: str,
    schema_path: str,
    db_path: str,
    client: LLMClient,
    limit: int | None = None,
) -> DB:
    schema = load_config(schema_path)
    db = DB(db_path)
    chapters = read_novel(novel_path)
    if limit is not None:
        chapters = chapters[:limit]  # 只处理前 N 章（试跑/控成本）

    # 1) 章节入库
    for ch in chapters:
        db.upsert_chapter(ch.index, ch.title, ch.text)

    # 2) 逐章抽取（断点续传：已有则复用）
    for ch in chapters:
        raw = db.get_extraction(ch.index)
        if raw is None:
            ext = extract_chapter(client, schema, ch)
            raw = ext.model_dump_json()
            db.save_extraction(ch.index, raw)

    # 3) 消歧合并（基于已落盘的抽取结果）
    for ch in chapters:
        raw = db.get_extraction(ch.index)
        if raw is None:
            continue
        ext = ChapterExtraction.model_validate_json(raw)
        resolve_extraction(db, schema, ch.index, ext)

    return db

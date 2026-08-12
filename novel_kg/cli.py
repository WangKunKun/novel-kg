import argparse
import os

from novel_kg.llm_client import OpenAICompatibleClient
from novel_kg.pipeline import run_pipeline


def main() -> None:
    ap = argparse.ArgumentParser(description="小说知识图谱 v1：抽取流水线")
    ap.add_argument("--novel", required=True, help="小说 txt 路径")
    ap.add_argument("--schema", default="config/novels/xuanjian.yaml", help="schema 配置")
    ap.add_argument("--db", default="data/novel.db", help="输出 SQLite 路径")
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL", "gpt-4o-mini"))
    ap.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL"))
    ap.add_argument("--api-key", default=os.environ.get("LLM_API_KEY"))
    args = ap.parse_args()

    client = OpenAICompatibleClient(args.model, args.base_url, args.api_key)
    db = run_pipeline(args.novel, args.schema, args.db, client)
    print(f"完成。实体 {sum(r['n'] for r in db.entity_counts())} 条，"
          f"关系 {len(db.list_relations())} 条。库：{args.db}")


if __name__ == "__main__":
    main()

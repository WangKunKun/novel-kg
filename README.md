# novel-kg

小说知识图谱分析工具（v1）。详见 `../docs/superpowers/specs/2026-08-12-novel-knowledge-graph-design.md`。

## 安装
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 运行测试
```bash
pytest -v
```

## 跑流水线（需要 LLM API key）
```bash
python -m novel_kg.cli --novel data/novels/sample.txt --schema config/novels/xuanjian.yaml --db data/novel.db
```

## 可视化
```bash
streamlit run novel_kg/viz_app.py
```

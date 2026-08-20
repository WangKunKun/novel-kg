import sys

from novel_kg import cli


class _FakeDB:
    """run_pipeline 的替身返回值，满足 main() 末尾的统计打印。"""

    def entity_counts(self):
        return []

    def list_relations(self):
        return []


def test_cli_limit_passed_to_pipeline(tmp_path, monkeypatch):
    novel = tmp_path / "book.txt"
    novel.write_text("====== 第1章 a ======\n正文\n", encoding="utf-8")

    captured: dict = {}

    def fake_run(novel_path, schema_path, db_path, client, limit=None):
        captured["limit"] = limit
        return _FakeDB()

    monkeypatch.setattr(cli, "run_pipeline", fake_run)
    monkeypatch.setattr(cli, "OpenAICompatibleClient", lambda *a, **k: object())
    monkeypatch.setattr(
        sys, "argv",
        ["cli", "--novel", str(novel), "--db", str(tmp_path / "t.db"), "--limit", "2"],
    )

    cli.main()
    assert captured["limit"] == 2  # --limit 解析成 int 并透传给 run_pipeline


def test_cli_prints_cache_stats_when_present(tmp_path, monkeypatch, capsys):
    novel = tmp_path / "book.txt"
    novel.write_text("====== 第1章 a ======\n正文\n", encoding="utf-8")

    class _FakeClient:
        cache_hit_tokens = 896
        prompt_tokens = 904
        completion_tokens = 100

    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: _FakeDB())
    monkeypatch.setattr(cli, "OpenAICompatibleClient", lambda *a, **k: _FakeClient())
    monkeypatch.setattr(
        sys, "argv",
        ["cli", "--novel", str(novel), "--db", str(tmp_path / "t.db")],
    )
    cli.main()
    out = capsys.readouterr().out
    assert "缓存" in out        # 打印缓存统计行
    assert "896" in out         # 显示命中 token 数

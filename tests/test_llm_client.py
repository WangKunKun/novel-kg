from novel_kg.llm_client import OpenAICompatibleClient


def test_record_usage_accumulates_tokens_and_cache_hit():
    c = OpenAICompatibleClient("m", None, "k")  # 不实际发请求
    c.record_usage({"prompt_tokens": 904, "completion_tokens": 100,
                    "prompt_cache_hit_tokens": 896})
    c.record_usage({"prompt_tokens": 904, "completion_tokens": 200,
                    "prompt_cache_hit_tokens": 896})
    assert c.prompt_tokens == 1808
    assert c.completion_tokens == 300
    assert c.cache_hit_tokens == 1792


def test_record_usage_reads_openai_style_cached_tokens():
    # 兼容 OpenAI 风格：prompt_tokens_details.cached_tokens
    c = OpenAICompatibleClient("m", None, "k")
    c.record_usage({"prompt_tokens": 100, "completion_tokens": 10,
                    "prompt_tokens_details": {"cached_tokens": 60}})
    assert c.cache_hit_tokens == 60

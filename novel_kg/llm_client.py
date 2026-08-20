from typing import Any, Protocol


class LLMClient(Protocol):
    """输入 system + user 提示，返回一个已解析的 JSON dict。"""

    def complete_json(self, system: str, user: str) -> dict[str, Any]: ...


class FakeLLMClient:
    """测试用：返回预设的 JSON，并记录调用。"""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.response = response or {"entities": [], "relations": []}
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        return self.response


class OpenAICompatibleClient:
    """生产用：兼容 OpenAI 接口（智谱 GLM 等可填 base_url 接入）。"""

    def __init__(self, model: str, base_url: str | None = None,
                 api_key: str | None = None) -> None:
        from openai import OpenAI

        kwargs: dict[str, Any] = {}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key:
            kwargs["api_key"] = api_key
        self.client = OpenAI(**kwargs)
        self.model = model
        # 累计 token 统计（含上下文缓存命中），供调用方报告节省情况
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cache_hit_tokens = 0

    def record_usage(self, usage: Any) -> None:
        """累加一次调用的 token 统计，兼容智谱 prompt_cache_hit_tokens
        与 OpenAI 风格 prompt_tokens_details.cached_tokens。"""
        d = usage if isinstance(usage, dict) else usage.model_dump()
        self.prompt_tokens += d.get("prompt_tokens", 0)
        self.completion_tokens += d.get("completion_tokens", 0)
        hit = d.get("prompt_cache_hit_tokens")
        if not hit:
            hit = (d.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        self.cache_hit_tokens += hit or 0

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        import json
        import time

        last_err: Exception | None = None
        for attempt in range(3):  # 失败退避重试：1s, 2s, 4s
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                )
                if resp.usage:
                    self.record_usage(resp.usage)
                return json.loads(resp.choices[0].message.content)
            except Exception as e:  # noqa: BLE001 - 重试包装，需捕获全部瞬时错误
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM 调用 3 次仍失败：{last_err}")

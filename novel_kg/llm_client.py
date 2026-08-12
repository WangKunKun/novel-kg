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
                return json.loads(resp.choices[0].message.content)
            except Exception as e:  # noqa: BLE001 - 重试包装，需捕获全部瞬时错误
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM 调用 3 次仍失败：{last_err}")

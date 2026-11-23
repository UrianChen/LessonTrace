"""大模型适配层。更换模型只改这一处：实现 LLMClient 并在 PROVIDERS 里登记。"""
from typing import Protocol

from ..config import get_settings


class LLMError(Exception):
    """模型调用失败（网络、限流、拒答、输出被截断等）。阶段任务会据此重试。"""


class LLMConfigError(LLMError):
    """配置问题（没填密钥、模型提供方写错），重试也没用，直接进入失败状态。"""


class LLMClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict) -> str:
        """按 schema 约束返回 JSON 文本（原始输出，不做解析）。"""
        ...


class AnthropicClient:
    def __init__(self, model: str, api_key: str, refusal_fallback: bool = True):
        import anthropic

        if not api_key:
            raise LLMConfigError("ANTHROPIC_API_KEY is not set in .env")
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=600.0)
        self.model = model
        self._fallback = refusal_fallback

    def complete_json(self, system: str, user: str, schema: dict) -> str:
        a = self._anthropic
        kwargs = dict(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        try:
            if self._fallback:
                # 模型因安全策略拒答时，由服务端换备用模型重跑同一请求
                resp = self._client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                resp = self._client.messages.create(**kwargs)
        except a.AuthenticationError as e:
            raise LLMConfigError(f"model API rejected the key: {e.message}") from e
        except a.RateLimitError as e:
            raise LLMError(f"rate limited: {e}") from e
        except a.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError(f"cannot reach model API: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMError("model declined the request")
        if resp.stop_reason == "max_tokens":
            raise LLMError("model output was cut off at max_tokens")
        text = next((b.text for b in resp.content if b.type == "text"), None)
        if text is None:
            raise LLMError("model returned no text")
        return text


PROVIDERS = {
    "anthropic": lambda s: AnthropicClient(s.llm_model, s.anthropic_api_key, s.llm_refusal_fallback),
}


def get_llm() -> LLMClient:
    s = get_settings()
    if s.llm_provider not in PROVIDERS:
        raise LLMConfigError(f"unknown LLM_PROVIDER: {s.llm_provider}")
    return PROVIDERS[s.llm_provider](s)

"""vLLM provider — extends OpenAI for vLLM-specific features.

vLLM exposes an OpenAI-compatible API. This provider adds:
- chat_template_kwargs (e.g., disable thinking mode for Qwen models)
- stream_options for usage stats in streaming mode
"""

from typing import Any

from temper_ai.llm.providers.openai import OpenAILLM


class VllmLLM(OpenAILLM):
    """vLLM provider — OpenAI-compatible with vLLM extras."""

    PROVIDER_NAME = "vllm"

    def _build_request(self, messages: list[dict], **kwargs: Any) -> dict:
        request = super()._build_request(messages, **kwargs)

        # Per-call kwargs override constructor defaults.
        # e.g., provider.complete(messages, chat_template_kwargs={"enable_thinking": True})
        if "chat_template_kwargs" in kwargs:
            request["chat_template_kwargs"] = kwargs["chat_template_kwargs"]
        else:
            request.setdefault("chat_template_kwargs", {"enable_thinking": True})

        # Request usage stats in streaming mode
        if kwargs.get("stream"):
            request.setdefault("stream_options", {"include_usage": True})

        return request

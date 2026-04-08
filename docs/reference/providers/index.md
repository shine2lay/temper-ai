[Home](../index.md) | [Tools](../tools/index.md) | **LLM Providers** | [Agent Types](../agents/index.md) | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# LLM Providers Reference

_Auto-generated from code. Do not edit manually._

Temper AI supports **6 LLM providers**. Set the provider in your [agent config](../agents/llm.md) or workflow `defaults:`.

| Name | Description |
|------|-------------|
| [`anthropic`](anthropic.md) | Provider for Anthropic Claude models. |
| [`claude`](claude.md) | Provider that shells out to the Claude Code CLI. |
| [`gemini`](gemini.md) | Provider for Google Gemini models. |
| [`ollama`](ollama.md) | Provider for Ollama (local models via OpenAI-compatible API). |
| [`openai`](openai.md) | Provider for OpenAI and OpenAI-compatible APIs. |
| [`vllm`](vllm.md) | vLLM provider — OpenAI-compatible with vLLM extras. |

## Extending

Implement `BaseLLM` and register it. Any [LLM agent](../agents/llm.md) can then reference it.

```python
from temper_ai.llm.providers import register_provider, BaseLLM

class MyProvider(BaseLLM):
    PROVIDER_NAME = "my_provider"

    def _build_request(self, messages, **kwargs): ...
    def _parse_response(self, response, latency_ms): ...
    def _get_headers(self): ...
    def _get_endpoint(self): ...
    def _consume_stream(self, response, on_chunk): ...

register_provider("my_provider", MyProvider, "http://localhost:8080")
```

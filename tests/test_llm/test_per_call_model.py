"""The agent's model: reaches the request for every shipped provider.

All agents on a provider share one instance, so the agent's model arrives as
a per-call kwarg. Each provider used to read only self.model; the YAML
setting was a silent no-op on all of them.
"""

from temper_ai.llm.providers.ollama import OllamaLLM
from temper_ai.llm.providers.openai import OpenAILLM
from temper_ai.llm.providers.vllm import VllmLLM

MSGS = [{"role": "user", "content": "hi"}]


def test_openai_family_sends_the_per_call_model():
    # Ollama/Vllm fix their own api_key; only OpenAI takes one.
    instances = [
        OpenAILLM(model="default-model", base_url="http://x", api_key="k"),
        OllamaLLM(model="default-model", base_url="http://x"),
        VllmLLM(model="default-model", base_url="http://x"),
    ]
    for llm in instances:
        name = type(llm).__name__
        assert llm._build_request(MSGS, model="agent-model")["model"] == "agent-model", name
        assert llm._build_request(MSGS)["model"] == "default-model", name

"""Claude Code LLM provider — runs prompts via the local Claude Code CLI.

Uses the `claude` CLI in headless mode (-p). Claude Code manages its own
tool-calling loop (Bash, file ops, search, web) so `complete()` returns the
final result with no tool_calls for the LLMService to chase.

Runs on your Max plan by default — no API key needed.

Usage in agent YAML:
    agent:
      name: my_coder
      provider: claude_code
      model: haiku          # sonnet (default), opus, haiku
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from temper_ai.llm.models import LLMResponse, LLMStreamChunk
from temper_ai.llm.providers.base import BaseLLM, StreamCallback

logger = logging.getLogger(__name__)

# Default tools Claude Code is allowed to use
_DEFAULT_ALLOWED_TOOLS = [
    "Bash", "Read", "Edit", "Write", "Glob", "Grep",
    "WebFetch", "WebSearch",
]


class ClaudeCodeLLM(BaseLLM):
    """Provider that shells out to the Claude Code CLI."""

    PROVIDER_NAME = "claude_code"

    def __init__(
        self,
        model: str = "sonnet",
        allowed_tools: list[str] | None = None,
        max_budget_usd: float | None = None,
        timeout: int = 300,
        cwd: str | None = None,
        mcp_config: str | None = None,
        # Absorb args the factory passes that we don't use
        base_url: str = "",
        api_key: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            model=model,
            base_url="",
            api_key=None,
            timeout=timeout,
            **kwargs,
        )
        self.allowed_tools = allowed_tools or _DEFAULT_ALLOWED_TOOLS
        self.max_budget_usd = max_budget_usd
        self.cwd = cwd
        self.mcp_config = mcp_config

    def complete(self, messages: list[dict], **kwargs: Any) -> LLMResponse:
        """Run a prompt through Claude Code CLI and return the result."""
        system_prompt, user_prompt = _extract_prompts(messages)

        cmd = [
            "npx", "-y", "@anthropic-ai/claude-code", "-p", user_prompt,
            "--output-format", "json",
            "--model", self.model,
        ]

        if self.allowed_tools:
            cmd += ["--allowedTools", ",".join(self.allowed_tools)]

        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]

        if self.max_budget_usd:
            cmd += ["--max-budget-usd", str(self.max_budget_usd)]

        if self.mcp_config:
            cmd += ["--mcp-config", self.mcp_config]

        cwd = kwargs.get("cwd") or self.cwd

        logger.info("claude_code: model=%s tools=%s mcp=%s cwd=%s", self.model, self.allowed_tools, self.mcp_config, cwd)

        # Build env: inherit current env but strip ANTHROPIC_API_KEY to force Max plan auth
        import os
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        # Use CLAUDE_CONFIG_DIR if set (for Docker with mounted credentials)
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            cwd=cwd,
            env=env,
        )

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            logger.error("Claude Code CLI failed (rc=%d): %s", proc.returncode, stderr[:500])
            return LLMResponse(
                content=f"Error: {stderr[:500]}",
                model=self.model,
                provider=self.PROVIDER_NAME,
                finish_reason="error",
            )

        return _parse_cli_output(proc.stdout, self.model)

    def stream(
        self,
        messages: list[dict],
        on_chunk: StreamCallback | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Stream via Claude Code CLI using stream-json output format."""
        system_prompt, user_prompt = _extract_prompts(messages)

        cmd = [
            "npx", "-y", "@anthropic-ai/claude-code", "-p", user_prompt,
            "--output-format", "stream-json",
            "--model", self.model,
            "--verbose",
        ]

        if self.allowed_tools:
            cmd += ["--allowedTools", ",".join(self.allowed_tools)]

        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]

        if self.max_budget_usd:
            cmd += ["--max-budget-usd", str(self.max_budget_usd)]

        if self.mcp_config:
            cmd += ["--mcp-config", self.mcp_config]

        cwd = kwargs.get("cwd") or self.cwd

        # Strip ANTHROPIC_API_KEY to force Max plan auth
        import os
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=env,
        )

        result_data = None
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = event.get("type", "")

                if etype == "assistant" and on_chunk:
                    for block in event.get("message", {}).get("content", []):
                        btype = block.get("type", "")
                        if btype == "text":
                            text = block.get("text", "")
                            if text:
                                on_chunk(LLMStreamChunk(content=text, done=False))
                        elif btype == "tool_use":
                            # Stream tool call activity so dashboard shows progress
                            tool_name = block.get("name", "?")
                            tool_input = block.get("input", {})
                            preview = str(tool_input)[:100]
                            on_chunk(LLMStreamChunk(
                                content=f"\n[Tool: {tool_name}] {preview}\n",
                                done=False,
                            ))
                        elif btype == "thinking":
                            thinking = block.get("thinking", "")
                            if thinking:
                                on_chunk(LLMStreamChunk(
                                    content=f"\n<thinking>{thinking[:200]}</thinking>\n",
                                    done=False,
                                ))

                elif etype == "user" and on_chunk:
                    # Tool results — show brief output
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "tool_result":
                            content = block.get("content", "")
                            if isinstance(content, str) and content:
                                preview = content[:150]
                                on_chunk(LLMStreamChunk(
                                    content=f"[Result] {preview}\n",
                                    done=False,
                                ))

                # Capture the final result
                if etype == "result":
                    result_data = event

            proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            return LLMResponse(
                content="Error: Claude Code CLI timed out",
                model=self.model,
                provider=self.PROVIDER_NAME,
                finish_reason="error",
            )

        if on_chunk:
            on_chunk(LLMStreamChunk(content="", done=True))

        if result_data:
            return _parse_cli_result(result_data, self.model)

        return LLMResponse(
            content="",
            model=self.model,
            provider=self.PROVIDER_NAME,
            finish_reason="error",
        )

    # --- Abstract method stubs (not used — we override complete/stream) ---

    def _get_headers(self) -> dict[str, str]:
        return {}

    def _get_endpoint(self) -> str:
        return ""

    def _build_request(self, messages: list[dict], **kwargs: Any) -> dict:
        return {}

    def _parse_response(self, response: dict, latency_ms: int = 0) -> LLMResponse:
        return LLMResponse(content="", model=self.model, provider=self.PROVIDER_NAME)

    def _consume_stream(self, response: Any, on_chunk: StreamCallback | None) -> LLMResponse:
        return LLMResponse(content="", model=self.model, provider=self.PROVIDER_NAME)


def _extract_prompts(messages: list[dict]) -> tuple[str, str]:
    """Extract system prompt and user prompt from messages list."""
    system = ""
    user_parts = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system = content
        elif role == "user":
            user_parts.append(content)
        elif role == "assistant":
            # Include assistant context for multi-turn
            user_parts.append(f"[Previous assistant response]: {content}")

    return system, "\n\n".join(user_parts)


def _parse_cli_output(raw: str, model: str) -> LLMResponse:
    """Parse JSON output from `claude -p --output-format json`."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return LLMResponse(content=raw.strip(), model=model, provider="claude_code")

    return _parse_cli_result(data, model)


def _parse_cli_result(data: dict, model: str) -> LLMResponse:
    """Parse a CLI result dict into LLMResponse."""
    usage = data.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_create = usage.get("cache_creation_input_tokens", 0)

    # Resolve actual model name from modelUsage if available
    model_usage = data.get("modelUsage", {})
    actual_model = next(iter(model_usage), model) if model_usage else model

    return LLMResponse(
        content=data.get("result", ""),
        model=actual_model,
        provider="claude_code",
        prompt_tokens=input_tokens + cache_read + cache_create,
        completion_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens + cache_read + cache_create,
        finish_reason=data.get("stop_reason", "end_turn"),
        # No tool_calls — Claude Code handles tools internally
        tool_calls=None,
        raw_response={
            "session_id": data.get("session_id"),
            "duration_ms": data.get("duration_ms"),
            "total_cost_usd": data.get("total_cost_usd"),
            "num_turns": data.get("num_turns"),
        },
    )

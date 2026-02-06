#!/usr/bin/env python3
"""Quick test: verify which Ollama models support native tool calling via /api/chat."""

import json
import sys
import time

import requests

OLLAMA_URL = "http://localhost:11434"

# Simple tool definition - ask the model to write a file
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file at the specified path",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file"
                    }
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a shell command and return its output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute"
                    }
                },
                "required": ["command"]
            }
        }
    }
]

PROMPT = """You are a coding assistant. Write a simple hello.py file that prints "Hello, World!" using the write_file tool. Then run it using the run_command tool."""

MODELS = [
    "qwen3:8b",
    "llama3.1:8b",
    "llama3.2:3b",
    "mistral:7b",
    "gemma3:4b",
    "phi4-mini",
]


def test_model(model: str) -> dict:
    """Test a single model for tool calling support."""
    result = {
        "model": model,
        "supports_tools": False,
        "tool_calls_made": 0,
        "tool_names": [],
        "error": None,
        "latency_s": 0,
        "response_text": "",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "tools": TOOLS,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512},
    }

    try:
        t0 = time.time()
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        result["latency_s"] = round(time.time() - t0, 1)

        if resp.status_code != 200:
            result["error"] = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return result

        data = resp.json()
        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls = message.get("tool_calls", [])

        result["response_text"] = content[:300] if content else "(no text)"

        if tool_calls:
            result["supports_tools"] = True
            result["tool_calls_made"] = len(tool_calls)
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "unknown")
                args = func.get("arguments", {})
                result["tool_names"].append(f"{name}({json.dumps(args)[:80]})")
        else:
            # Check if the model tried to output tool calls as text
            if "<tool_call>" in content or '"name"' in content:
                result["response_text"] = "(text-based tool call attempt) " + content[:200]

    except requests.exceptions.Timeout:
        result["error"] = "Timeout (120s)"
    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def main():
    models = sys.argv[1:] if len(sys.argv) > 1 else MODELS

    print("=" * 80)
    print("OLLAMA TOOL CALLING TEST")
    print("=" * 80)
    print(f"Testing {len(models)} models with /api/chat + native tools\n")

    results = []
    for model in models:
        print(f"Testing {model}...", end=" ", flush=True)
        r = test_model(model)
        results.append(r)

        if r["error"]:
            print(f"ERROR: {r['error']}")
        elif r["supports_tools"]:
            print(f"OK - {r['tool_calls_made']} tool calls in {r['latency_s']}s")
            for tc in r["tool_names"]:
                print(f"    -> {tc}")
        else:
            print(f"NO TOOL CALLS ({r['latency_s']}s)")
            if r["response_text"]:
                print(f"    text: {r['response_text'][:120]}")
        print()

    # Summary table
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"{'Model':<20} {'Tools?':<8} {'# Calls':<8} {'Latency':<10} {'Status'}")
    print("-" * 80)
    for r in results:
        status = "ERROR" if r["error"] else ("YES" if r["supports_tools"] else "NO")
        calls = r["tool_calls_made"]
        lat = f"{r['latency_s']}s"
        emoji = "PASS" if r["supports_tools"] else ("FAIL" if not r["error"] else "ERR")
        print(f"{r['model']:<20} {status:<8} {calls:<8} {lat:<10} {emoji}")

    # Recommend best models
    good = [r for r in results if r["supports_tools"]]
    if good:
        print(f"\nModels with working tool calling: {len(good)}/{len(results)}")
        fastest = min(good, key=lambda x: x["latency_s"])
        most_calls = max(good, key=lambda x: x["tool_calls_made"])
        print(f"  Fastest: {fastest['model']} ({fastest['latency_s']}s)")
        print(f"  Most tool calls: {most_calls['model']} ({most_calls['tool_calls_made']} calls)")
    else:
        print("\nNo models produced native tool calls.")


if __name__ == "__main__":
    main()

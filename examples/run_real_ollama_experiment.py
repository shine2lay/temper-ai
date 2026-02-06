#!/usr/bin/env python3
"""
M5 Real Ollama Experiment - Actual LLM calls with real performance metrics

Uses actual Ollama models to test product extraction with real quality scoring.
"""

import asyncio
import json
import time
from collections import defaultdict

import httpx


# ANSI colors
class Colors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RED = '\033[91m'

# Real product extraction test cases
TEST_PRODUCTS = [
    {
        "raw_text": "MacBook Pro 16-inch M3 Max chip 36GB unified memory 1TB SSD storage Space Black $3499.99 Free shipping",
        "expected": {
            "name": "MacBook Pro 16-inch",
            "specs": "M3 Max, 36GB memory, 1TB SSD",
            "color": "Space Black",
            "price": 3499.99,
        },
        "difficulty": "simple"
    },
    {
        "raw_text": "Sony WH1000XM5 wireless noise canceling over-ear headphones black thirty-hour battery life three hundred ninety nine dollars",
        "expected": {
            "name": "Sony WH-1000XM5",
            "specs": "wireless, noise canceling, 30h battery",
            "color": "black",
            "price": 399.0,
        },
        "difficulty": "medium"
    },
    {
        "raw_text": "65\" Samsung QLED Smart TV QN90C with Neo Quantum HDR+, originally $2,199 now on sale for 1899 USD, includes free wall mount",
        "expected": {
            "name": "Samsung 65-inch QLED Smart TV QN90C",
            "specs": "Neo Quantum HDR+, Smart TV",
            "color": None,
            "price": 1899.0,
        },
        "difficulty": "complex"
    },
    {
        "raw_text": "Dyson V15 Detect Cordless Vacuum - Features: HEPA filtration, laser dust detection - Color: Yellow/Nickel - MSRP $649.99",
        "expected": {
            "name": "Dyson V15 Detect",
            "specs": "Cordless, HEPA, laser dust detection",
            "color": "Yellow",
            "price": 649.99,
        },
        "difficulty": "medium"
    },
    {
        "raw_text": "Apple Watch Series 9 GPS, case size: 45mm, Midnight Aluminum Case with matching Sport Band, retail price four hundred twenty-nine dollars",
        "expected": {
            "name": "Apple Watch Series 9",
            "specs": "GPS, 45mm",
            "color": "Midnight Aluminum",
            "price": 429.0,
        },
        "difficulty": "complex"
    },
]

EXTRACTION_PROMPT = """Extract product information from the following text and return ONLY a JSON object with these exact fields:
- name: product name (string)
- specs: key specifications (string, not an object or array)
- color: product color (string or null if not mentioned)
- price: numeric price in dollars (number)

IMPORTANT: Use simple strings for name, specs, and color. Do NOT use nested objects, arrays, or sets.

Text: {text}

Return only the JSON object with no markdown formatting:"""


class OllamaClient:
    """Async client for Ollama API."""

    def __init__(self, base_url="http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0)  # 5 minutes for local inference

    async def generate(self, model: str, prompt: str) -> tuple[str, dict]:
        """Generate response from model."""
        start_time = time.time()

        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1}  # Low temp for consistent extraction
                }
            )
            response.raise_for_status()
            result = response.json()

            duration = time.time() - start_time

            metadata = {
                "duration": duration,
                "tokens": result.get("eval_count", 0) + result.get("prompt_eval_count", 0),
                "prompt_tokens": result.get("prompt_eval_count", 0),
                "completion_tokens": result.get("eval_count", 0),
            }

            return result.get("response", ""), metadata

        except httpx.TimeoutException as e:
            print(f"  {Colors.RED}Timeout with {model}: Request exceeded 300s{Colors.RESET}")
            return "", {"duration": 0, "tokens": 0, "error": "timeout", "error_detail": str(e)}
        except httpx.HTTPStatusError as e:
            print(f"  {Colors.RED}HTTP Error with {model}: {e.response.status_code} - {e.response.text[:100]}{Colors.RESET}")
            return "", {"duration": 0, "tokens": 0, "error": "http_error", "error_detail": str(e)}
        except Exception as e:
            print(f"  {Colors.RED}Error with {model}: {type(e).__name__} - {str(e)[:100]}{Colors.RESET}")
            return "", {"duration": 0, "tokens": 0, "error": type(e).__name__, "error_detail": str(e)}

    async def close(self):
        await self.client.aclose()


class QualityScorer:
    """Score extraction quality against expected results."""

    @staticmethod
    def parse_json(response: str) -> dict:
        """Extract JSON from response."""
        try:
            # Strip markdown code blocks if present
            response = response.strip()
            if response.startswith("```"):
                # Remove opening ```json or ```
                lines = response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                # Remove closing ```
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = "\n".join(lines)

            # Find JSON in response
            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start == -1 or json_end == 0:
                print(f"    {Colors.YELLOW}⚠ No JSON found in response: {response[:100]}...{Colors.RESET}")
                return None

            json_str = response[json_start:json_end]

            # Try to parse
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # Try to fix common issues
                # Replace Python set notation {item1, item2} with array [item1, item2]
                # This is a heuristic - look for {"word", "word"} patterns
                import re
                fixed = re.sub(r':\s*\{([^{}:]+)\}', r': [\1]', json_str)
                try:
                    return json.loads(fixed)
                except:
                    raise  # Re-raise original error

        except json.JSONDecodeError as e:
            print(f"    {Colors.YELLOW}⚠ JSON parse failed: {e}. Content: {response[:100]}...{Colors.RESET}")
            return None
        except Exception as e:
            print(f"    {Colors.YELLOW}⚠ Unexpected error parsing: {type(e).__name__}{Colors.RESET}")
            return None

    @staticmethod
    def score(extracted: dict, expected: dict) -> tuple[float, dict]:
        """Score extraction quality (0.0-1.0)."""
        if extracted is None:
            return 0.0, {"parse_failed": True}

        scores = {}

        # Name (40%)
        name_score = QualityScorer._score_field(
            extracted.get("name", ""),
            expected["name"],
            is_text=True
        )
        scores["name"] = name_score

        # Specs (30%)
        specs_score = QualityScorer._score_field(
            extracted.get("specs", ""),
            expected["specs"],
            is_text=True,
            fuzzy=True
        )
        scores["specs"] = specs_score

        # Color (10%)
        color_score = QualityScorer._score_field(
            extracted.get("color"),
            expected["color"],
            is_text=True,
            allow_none=True
        )
        scores["color"] = color_score

        # Price (20%)
        price_score = QualityScorer._score_price(
            extracted.get("price"),
            expected["price"]
        )
        scores["price"] = price_score

        # Weighted total
        quality = (
            name_score * 0.4 +
            specs_score * 0.3 +
            color_score * 0.1 +
            price_score * 0.2
        )

        scores["overall"] = quality
        return quality, scores

    @staticmethod
    def _score_field(extracted, expected, is_text=False, fuzzy=False, allow_none=False):
        """Score individual field."""
        if expected is None and allow_none:
            return 1.0 if extracted is None else 0.5

        if not extracted:
            return 0.0

        if is_text:
            extracted_lower = str(extracted).lower()
            expected_lower = str(expected).lower()

            if fuzzy:
                # Check for keyword overlap
                expected_words = set(expected_lower.split())
                extracted_words = set(extracted_lower.split())
                overlap = len(expected_words & extracted_words)
                return min(1.0, overlap / max(len(expected_words), 1) * 1.5)
            else:
                # Exact/substring match
                if expected_lower in extracted_lower or extracted_lower in expected_lower:
                    return 1.0
                return 0.3  # Partial credit

        return 1.0 if extracted == expected else 0.0

    @staticmethod
    def _score_price(extracted, expected):
        """Score price field."""
        try:
            extracted_num = float(extracted) if extracted else 0
            expected_num = float(expected)

            diff = abs(extracted_num - expected_num) / expected_num

            if diff < 0.01:
                return 1.0
            elif diff < 0.05:
                return 0.8
            elif diff < 0.10:
                return 0.5
            else:
                return 0.2
        except:
            return 0.0


async def test_model(client: OllamaClient, model: str, num_samples: int = 5):
    """Test a model on real product extraction tasks."""
    results = []

    print(f"  Testing {model}...")

    for i in range(num_samples):
        # Pick random product
        import random
        product = random.choice(TEST_PRODUCTS)

        # Generate prompt
        prompt = EXTRACTION_PROMPT.format(text=product["raw_text"])

        # Call model
        response, metadata = await client.generate(model, prompt)

        # Parse and score
        extracted = QualityScorer.parse_json(response)
        quality, score_breakdown = QualityScorer.score(extracted, product["expected"])

        result_entry = {
            "quality": quality,
            "duration": metadata["duration"],
            "tokens": metadata["tokens"],
            "difficulty": product["difficulty"],
            "extracted": extracted,
            "expected": product["expected"],
            "score_breakdown": score_breakdown,
        }

        # Track errors
        if "error" in metadata:
            result_entry["error"] = True
            result_entry["metadata"] = metadata

        results.append(result_entry)

    # Analyze results
    avg_quality = sum(r["quality"] for r in results) / len(results)
    avg_duration = sum(r["duration"] for r in results) / len(results)
    avg_tokens = sum(r["tokens"] for r in results) / len(results)

    # Cost estimation (rough)
    cost_per_1m_tokens = 0.10  # Generic estimate
    avg_cost = (avg_tokens / 1_000_000) * cost_per_1m_tokens

    # By difficulty
    by_difficulty = defaultdict(list)
    for r in results:
        by_difficulty[r["difficulty"]].append(r["quality"])

    difficulty_scores = {
        diff: sum(scores) / len(scores)
        for diff, scores in by_difficulty.items()
    }

    return {
        "model": model,
        "avg_quality": avg_quality,
        "avg_duration": avg_duration,
        "avg_cost": avg_cost,
        "avg_tokens": avg_tokens,
        "results": results,
        "by_difficulty": difficulty_scores,
    }


async def main():
    print("\n" + "=" * 100)
    print(f"{Colors.BOLD}M5 REAL OLLAMA EXPERIMENT - Live Model Testing{Colors.RESET}")
    print("=" * 100)

    print(f"\n{Colors.BOLD}Configuration:{Colors.RESET}")
    print("  • Real Ollama API calls")
    print(f"  • Test products: {len(TEST_PRODUCTS)}")
    print("  • Samples per model: 5")
    print("  • Quality scoring: Actual extraction vs expected")

    # Get available models
    import subprocess
    result = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True
    )

    available_models = []
    for line in result.stdout.split("\n")[1:]:  # Skip header
        if line.strip():
            model_name = line.split()[0]
            if model_name:
                available_models.append(model_name)

    print(f"\n{Colors.BOLD}Available Models ({len(available_models)}):{Colors.RESET}")
    for model in available_models[:15]:  # Show first 15
        print(f"  • {model}")

    # Select models to test - prioritize coding models and high performers
    coding_models = [m for m in available_models if 'code' in m.lower() or 'wizard' in m.lower() or 'star' in m.lower()]
    other_models = [m for m in available_models if m not in coding_models]

    # Test coding models + top performers
    models_to_test = coding_models + other_models[:8]  # Coding models + 8 others
    models_to_test = models_to_test[:12]  # Cap at 12 models

    print(f"\n{Colors.BOLD}Testing {len(models_to_test)} models:{Colors.RESET}")
    for model in models_to_test:
        print(f"  • {model}")

    coding_count = len([m for m in models_to_test if 'code' in m.lower() or 'wizard' in m.lower() or 'star' in m.lower()])
    print(f"\n{Colors.CYAN}📊 Model Breakdown:{Colors.RESET}")
    print(f"  • Coding models: {coding_count}")
    print(f"  • General models: {len(models_to_test) - coding_count}")

    print(f"\n{Colors.YELLOW}⚠️  This will make {len(models_to_test) * 5} real LLM calls (~2-3 minutes){Colors.RESET}")
    print()

    # Run tests
    client = OllamaClient()

    print(f"{Colors.CYAN}{'─' * 100}{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}RUNNING EXPERIMENTS{Colors.RESET}")
    print(f"{Colors.CYAN}{'─' * 100}{Colors.RESET}\n")

    # Test all models in parallel for speed
    tasks = [test_model(client, model) for model in models_to_test]
    all_results = await asyncio.gather(*tasks)

    await client.close()

    # Sort by quality
    all_results.sort(key=lambda x: x["avg_quality"], reverse=True)

    # Analyze errors
    error_summary = defaultdict(lambda: {"count": 0, "models": []})
    for result in all_results:
        for exec_result in result["results"]:
            if "error" in exec_result and exec_result.get("duration") == 0:
                error_type = "unknown"
                if "metadata" in exec_result:
                    error_type = exec_result["metadata"].get("error", "unknown")
                error_summary[error_type]["count"] += 1
                if result["model"] not in error_summary[error_type]["models"]:
                    error_summary[error_type]["models"].append(result["model"])

    # Display results
    print(f"\n{Colors.CYAN}{'─' * 100}{Colors.RESET}")
    print(f"{Colors.BOLD}RESULTS{Colors.RESET}")
    print(f"{Colors.CYAN}{'─' * 100}{Colors.RESET}\n")

    print(f"{'Rank':<5s} {'Model':<35s} {'Quality':>10s} {'Duration':>12s} {'Tokens':>10s} {'Simple':>10s} {'Complex':>10s}")
    print("─" * 100)

    for rank, result in enumerate(all_results, 1):
        quality_color = Colors.GREEN if result["avg_quality"] >= 0.75 else (Colors.YELLOW if result["avg_quality"] >= 0.60 else Colors.RED)

        medal = ""
        if rank == 1:
            medal = "🥇"
        elif rank == 2:
            medal = "🥈"
        elif rank == 3:
            medal = "🥉"

        # Get difficulty breakdown
        simple_q = result["by_difficulty"].get("simple", 0)
        complex_q = result["by_difficulty"].get("complex", 0)

        print(f"{rank:<3d} {medal:<2s} {result['model']:<35s} "
              f"{quality_color}{result['avg_quality']:>10.3f}{Colors.RESET} "
              f"{result['avg_duration']:>10.2f}s  "
              f"{result['avg_tokens']:>10.0f}  "
              f"{simple_q:>10.3f}  "
              f"{complex_q:>10.3f}")

    # Detailed analysis
    print(f"\n{Colors.BOLD}Detailed Analysis:{Colors.RESET}\n")

    # Top 3
    print(f"{Colors.BOLD}Top 3 Models:{Colors.RESET}")
    for rank, result in enumerate(all_results[:3], 1):
        print(f"  {rank}. {result['model']:<35s} - Quality: {result['avg_quality']:.3f}, "
              f"Speed: {result['avg_duration']:.2f}s")

    # Best by metric
    fastest = min(all_results, key=lambda x: x["avg_duration"])
    most_consistent = min(all_results,
                         key=lambda x: max(x["by_difficulty"].values()) - min(x["by_difficulty"].values())
                                      if len(x["by_difficulty"]) > 1 else float('inf'))

    print(f"\n{Colors.BOLD}Special Mentions:{Colors.RESET}")
    print(f"  ⚡ Fastest: {fastest['model']} ({fastest['avg_duration']:.2f}s)")
    print(f"  📊 Most Consistent: {most_consistent['model']}")

    # Complexity handling
    print(f"\n{Colors.BOLD}Complexity Handling:{Colors.RESET}")
    complexity_gaps = [
        (r["model"],
         r["by_difficulty"].get("simple", 0) - r["by_difficulty"].get("complex", 0))
        for r in all_results
        if "simple" in r["by_difficulty"] and "complex" in r["by_difficulty"]
    ]

    if complexity_gaps:
        best_gap = min(complexity_gaps, key=lambda x: abs(x[1]))
        print(f"  • Best (smallest gap): {best_gap[0]} (gap: {best_gap[1]:.3f})")

        worst_gap = max(complexity_gaps, key=lambda x: x[1])
        print(f"  • Struggles most: {worst_gap[0]} (gap: {worst_gap[1]:.3f})")

    # Sample outputs
    print(f"\n{Colors.BOLD}Sample Extraction (Best Model: {all_results[0]['model']}):{Colors.RESET}")
    sample = all_results[0]["results"][0]
    print(f"  Expected: {sample['expected']}")
    print(f"  Extracted: {sample['extracted']}")
    print(f"  Quality: {sample['quality']:.3f}")
    print(f"  Breakdown: {sample['score_breakdown']}")

    # Error summary
    if error_summary:
        print(f"\n{Colors.BOLD}{Colors.RED}Error Summary:{Colors.RESET}")
        total_errors = sum(info["count"] for info in error_summary.values())
        total_calls = len(models_to_test) * 5
        print(f"  Total errors: {total_errors}/{total_calls} calls ({total_errors/total_calls*100:.1f}%)")
        print(f"\n  {Colors.BOLD}By Error Type:{Colors.RESET}")
        for error_type, info in sorted(error_summary.items(), key=lambda x: x[1]["count"], reverse=True):
            models_str = ", ".join(info["models"][:3])
            if len(info["models"]) > 3:
                models_str += f" (+{len(info['models'])-3} more)"
            print(f"    • {error_type}: {info['count']} errors")
            print(f"      Models: {models_str}")

    print("\n" + "=" * 100)
    print(f"{Colors.GREEN}{Colors.BOLD}✓ REAL OLLAMA EXPERIMENT COMPLETE{Colors.RESET}")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

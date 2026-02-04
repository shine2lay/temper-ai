#!/usr/bin/env python3
"""
M5 Improved Multi-Lever Optimization - Better Model × Prompt Search

Improvements:
1. Test proven good models (mistral:7b, llama3.2:3b from earlier experiments)
2. More samples (15 per config) for statistical significance
3. Improved prompt strategies
4. Debug output to see actual extractions
5. Iterative prompt refinement
"""

import asyncio
import json
import time
from collections import defaultdict
from typing import Dict, List, Tuple, Optional
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
    MAGENTA = '\033[95m'
    DIM = '\033[2m'

# Test cases - using the same ones that worked before
TEST_CASES = [
    {"text": "MacBook Pro 16-inch M3 Max chip 36GB unified memory 1TB SSD storage Space Black $3499.99 Free shipping",
     "expected": {"name": "MacBook Pro 16-inch", "specs": "M3 Max, 36GB memory, 1TB SSD", "color": "Space Black", "price": 3499.99}},
    {"text": "Sony WH1000XM5 wireless noise canceling over-ear headphones black thirty-hour battery life three hundred ninety nine dollars",
     "expected": {"name": "Sony WH-1000XM5", "specs": "wireless, noise canceling, 30h battery", "color": "black", "price": 399.0}},
    {"text": "65\" Samsung QLED Smart TV QN90C with Neo Quantum HDR+, originally $2,199 now on sale for 1899 USD",
     "expected": {"name": "Samsung 65-inch QLED Smart TV QN90C", "specs": "Neo Quantum HDR+, Smart TV", "color": None, "price": 1899.0}},
    {"text": "Dyson V15 Detect Cordless Vacuum - Features: HEPA filtration, laser dust detection - Color: Yellow/Nickel - MSRP $649.99",
     "expected": {"name": "Dyson V15 Detect", "specs": "Cordless, HEPA, laser dust detection", "color": "Yellow", "price": 649.99}},
    {"text": "Apple Watch Series 9 GPS, case size: 45mm, Midnight Aluminum Case with matching Sport Band, retail price four hundred twenty-nine dollars",
     "expected": {"name": "Apple Watch Series 9", "specs": "GPS, 45mm", "color": "Midnight Aluminum", "price": 429.0}},
]

# Improved prompt strategies
PROMPT_STRATEGIES = {
    "baseline": {
        "name": "Baseline (from earlier experiment)",
        "template": """Extract product information from the following text and return ONLY a JSON object with these exact fields:
- name: product name (string)
- specs: key specifications (string, not an object or array)
- color: product color (string or null if not mentioned)
- price: numeric price in dollars (number)

IMPORTANT:
- Use simple strings for name, specs, and color. Do NOT use nested objects, arrays, or sets.
- If multiple prices mentioned, extract the most relevant one (MSRP or current price)
- Convert text numbers to numeric format (e.g., "thirty-nine" → 39)

Text: {text}

Return only the JSON object with no markdown formatting:"""
    },

    "strict_json": {
        "name": "Strict JSON Format",
        "template": """You are a JSON extraction bot. Extract product data and output valid JSON only.

Required fields (exact format):
{{"name": "string", "specs": "string", "color": "string or null", "price": number}}

Rules:
- specs must be a simple string, not nested objects
- price must be a number (no $ or commas)
- Convert word numbers to digits: "five hundred" = 500
- If multiple prices, use the final/current price

Text: {text}

JSON output:"""
    },

    "few_shot_examples": {
        "name": "Few-Shot with Examples",
        "template": """Extract product info as JSON. See examples:

Input: "iPhone 15 Pro 256GB Blue $999"
Output: {{"name": "iPhone 15 Pro", "specs": "256GB", "color": "Blue", "price": 999.0}}

Input: "Sony TV fifty-five inch 4K OLED, price: two thousand dollars"
Output: {{"name": "Sony 55-inch TV", "specs": "4K OLED", "color": null, "price": 2000.0}}

Input: "Gaming laptop RTX 4090 32GB RAM Black originally $3499 now $2999"
Output: {{"name": "Gaming Laptop", "specs": "RTX 4090, 32GB RAM", "color": "Black", "price": 2999.0}}

Now extract:
Input: {text}
Output:"""
    },

    "explicit_steps": {
        "name": "Explicit Step-by-Step",
        "template": """Extract product information by following these steps:

1. Find product name (the main product, not accessories)
2. Extract key specs (capacity, technology, features) as comma-separated string
3. Identify color (or null if not mentioned)
4. Find price in USD (convert text numbers, use current price if multiple)

Text: {text}

Now output as JSON with fields: name, specs, color, price
JSON:"""
    },

    "ultra_strict": {
        "name": "Ultra Strict Format",
        "template": """OUTPUT VALID JSON ONLY. NO EXPLANATIONS.

Extract from text below. Format:
{{"name": "Product Name", "specs": "spec1, spec2", "color": "Color or null", "price": NUMBER}}

CRITICAL:
- specs is a STRING (not object/array)
- price is a NUMBER (not string)
- Convert "five hundred" to 500
- If sale price exists, use that

TEXT: {text}

JSON:"""
    },
}


class OllamaClient:
    def __init__(self, base_url="http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0)

    async def generate(self, model: str, prompt: str) -> Tuple[str, Dict]:
        start_time = time.time()
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1}}
            )
            response.raise_for_status()
            result = response.json()
            duration = time.time() - start_time
            return result.get("response", ""), {"duration": duration, "tokens": result.get("eval_count", 0) + result.get("prompt_eval_count", 0), "success": True}
        except Exception as e:
            return "", {"duration": 0, "tokens": 0, "success": False, "error": str(e)}

    async def close(self):
        await self.client.aclose()


class QualityScorer:
    @staticmethod
    def parse_json(response: str) -> Optional[Dict]:
        try:
            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = "\n".join(lines)

            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start == -1 or json_end == 0:
                return None

            json_str = response[json_start:json_end]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                import re
                fixed = re.sub(r':\s*\{([^{}:]+)\}', r': [\1]', json_str)
                try:
                    return json.loads(fixed)
                except:
                    return None
        except:
            return None

    @staticmethod
    def score(extracted: Optional[Dict], expected: Dict) -> Tuple[float, Dict]:
        if extracted is None:
            return 0.0, {"name": 0, "specs": 0, "color": 0, "price": 0, "parse_failed": True}

        scores = {}

        # Name (40%)
        name_score = QualityScorer._score_text(extracted.get("name", ""), expected["name"])
        scores["name"] = name_score

        # Specs (30%)
        specs_score = QualityScorer._score_text_fuzzy(extracted.get("specs", ""), expected["specs"])
        scores["specs"] = specs_score

        # Color (10%)
        color_expected = expected.get("color")
        color_extracted = extracted.get("color")
        if color_expected is None:
            color_score = 1.0 if color_extracted is None else 0.5
        else:
            color_score = QualityScorer._score_text(color_extracted or "", color_expected)
        scores["color"] = color_score

        # Price (20%)
        price_score = QualityScorer._score_price(extracted.get("price"), expected["price"])
        scores["price"] = price_score

        overall = name_score * 0.4 + specs_score * 0.3 + color_score * 0.1 + price_score * 0.2
        scores["overall"] = overall
        return overall, scores

    @staticmethod
    def _score_text(extracted: str, expected: str) -> float:
        extracted_lower = str(extracted).lower()
        expected_lower = str(expected).lower()
        if expected_lower in extracted_lower or extracted_lower in expected_lower:
            return 1.0
        return 0.3

    @staticmethod
    def _score_text_fuzzy(extracted: str, expected: str) -> float:
        expected_words = set(str(expected).lower().split())
        extracted_words = set(str(extracted).lower().split())
        overlap = len(expected_words & extracted_words)
        return min(1.0, overlap / max(len(expected_words), 1) * 1.5)

    @staticmethod
    def _score_price(extracted, expected) -> float:
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


class ImprovedMultiLeverOptimizer:
    def __init__(self, client: OllamaClient):
        self.client = client
        self.results_grid = {}
        self.debug_samples = {}  # Store sample extractions for debugging

    async def test_configuration(self, model: str, prompt_key: str, num_samples: int = 15, debug: bool = False) -> Dict:
        prompt_strategy = PROMPT_STRATEGIES[prompt_key]
        results = []

        for i, test_case in enumerate(TEST_CASES):
            prompt = prompt_strategy["template"].format(text=test_case["text"])
            response, metadata = await self.client.generate(model, prompt)

            extracted = QualityScorer.parse_json(response)
            quality, breakdown = QualityScorer.score(extracted, test_case["expected"])

            results.append({
                "quality": quality,
                "duration": metadata["duration"],
                "success": metadata["success"],
                "breakdown": breakdown,
                "extracted": extracted,
                "expected": test_case["expected"],
            })

            # Store first sample for debugging
            if i == 0 and debug:
                self.debug_samples[(model, prompt_key)] = {
                    "text": test_case["text"],
                    "extracted": extracted,
                    "expected": test_case["expected"],
                    "quality": quality,
                    "breakdown": breakdown,
                }

        avg_quality = sum(r["quality"] for r in results) / len(results)
        avg_duration = sum(r["duration"] for r in results if r["success"]) / max(1, sum(1 for r in results if r["success"]))
        success_rate = sum(1 for r in results if r["success"]) / len(results)

        # Calculate breakdown averages
        avg_breakdown = {
            "name": sum(r["breakdown"]["name"] for r in results) / len(results),
            "specs": sum(r["breakdown"]["specs"] for r in results) / len(results),
            "color": sum(r["breakdown"]["color"] for r in results) / len(results),
            "price": sum(r["breakdown"]["price"] for r in results) / len(results),
        }

        return {
            "model": model,
            "prompt": prompt_key,
            "avg_quality": avg_quality,
            "avg_duration": avg_duration,
            "success_rate": success_rate,
            "num_samples": len(results),
            "breakdown": avg_breakdown,
        }

    async def grid_search(self, models: List[str], prompt_keys: List[str], num_samples: int = 15) -> Dict:
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}IMPROVED GRID SEARCH: MODEL * PROMPT OPTIMIZATION{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        print(f"  {Colors.BOLD}Search Space:{Colors.RESET}")
        print(f"    Models: {len(models)}")
        for model in models:
            print(f"      • {model}")
        print(f"\n    Prompts: {len(prompt_keys)}")
        for key in prompt_keys:
            print(f"      • {PROMPT_STRATEGIES[key]['name']}")
        print(f"\n    Configurations: {len(models) * len(prompt_keys)}")
        print(f"    Samples per config: {num_samples}")
        print(f"    Total tests: {len(models) * len(prompt_keys) * num_samples}")

        print(f"\n  {Colors.YELLOW}Running grid search with debug output...{Colors.RESET}\n")

        tasks = []
        configs = []

        for model in models:
            for prompt_key in prompt_keys:
                tasks.append(self.test_configuration(model, prompt_key, num_samples, debug=True))
                configs.append((model, prompt_key))

        results = await asyncio.gather(*tasks)

        for i, (model, prompt_key) in enumerate(configs):
            self.results_grid[(model, prompt_key)] = results[i]

            # Show progress
            print(f"    ✓ {model:<30s} + {PROMPT_STRATEGIES[prompt_key]['name']:<30s}: {results[i]['avg_quality']:.3f}")

        print(f"\n  {Colors.GREEN}✓ Grid search complete{Colors.RESET}\n")
        return self.results_grid

    def show_debug_samples(self):
        """Show sample extractions to understand what's failing."""
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}DEBUG: Sample Extractions{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        # Find best and worst
        best = max(self.results_grid.items(), key=lambda x: x[1]["avg_quality"])
        worst = min(self.results_grid.items(), key=lambda x: x[1]["avg_quality"])

        for label, config in [("BEST", best[0]), ("WORST", worst[0])]:
            if config not in self.debug_samples:
                continue

            sample = self.debug_samples[config]
            model, prompt = config

            print(f"  {Colors.BOLD}{label}: {model} + {PROMPT_STRATEGIES[prompt]['name']}{Colors.RESET}")
            print(f"    Quality: {sample['quality']:.3f}")
            print(f"    Breakdown: Name={sample['breakdown']['name']:.2f}, Specs={sample['breakdown']['specs']:.2f}, "
                  f"Color={sample['breakdown']['color']:.2f}, Price={sample['breakdown']['price']:.2f}")
            print(f"\n    Text: {sample['text'][:80]}...")
            print(f"\n    Expected: {json.dumps(sample['expected'], indent=6)}")
            print(f"    Extracted: {json.dumps(sample['extracted'], indent=6) if sample['extracted'] else 'PARSE FAILED'}")
            print()

    def analyze_results(self) -> Dict:
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}RESULTS ANALYSIS{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        # Best configuration
        best_config = max(self.results_grid.items(), key=lambda x: x[1]["avg_quality"])
        best_model, best_prompt = best_config[0]
        best_metrics = best_config[1]

        # Quality grid
        print(f"  {Colors.BOLD}Quality Grid:{Colors.RESET}\n")
        models = sorted(set(model for model, _ in self.results_grid.keys()))
        prompts = sorted(set(prompt for _, prompt in self.results_grid.keys()))

        # Header
        print(f"    {'Model':<30s}", end="")
        for prompt in prompts:
            prompt_name = PROMPT_STRATEGIES[prompt]["name"][:15]
            print(f" {prompt_name:>15s}", end="")
        print()
        print(f"    {'-' * (30 + 16 * len(prompts))}")

        # Rows
        for model in models:
            print(f"    {model:<30s}", end="")
            for prompt in prompts:
                if (model, prompt) in self.results_grid:
                    quality = self.results_grid[(model, prompt)]["avg_quality"]
                    if model == best_model and prompt == best_prompt:
                        print(f" {Colors.GREEN}{Colors.BOLD}{quality:>15.3f}{Colors.RESET}", end="")
                    elif quality >= 0.90:
                        print(f" {Colors.GREEN}{quality:>15.3f}{Colors.RESET}", end="")
                    elif quality >= 0.80:
                        print(f" {Colors.YELLOW}{quality:>15.3f}{Colors.RESET}", end="")
                    else:
                        print(f" {Colors.RED}{quality:>15.3f}{Colors.RESET}", end="")
                else:
                    print(f" {'N/A':>15s}", end="")
            print()

        print(f"\n  {Colors.BOLD}🏆 Best Configuration:{Colors.RESET}")
        print(f"    Model:   {Colors.GREEN}{best_model}{Colors.RESET}")
        print(f"    Prompt:  {Colors.GREEN}{PROMPT_STRATEGIES[best_prompt]['name']}{Colors.RESET}")
        print(f"    Quality: {Colors.GREEN}{best_metrics['avg_quality']:.3f}{Colors.RESET}")
        print(f"    Speed:   {best_metrics['avg_duration']:.2f}s")
        print(f"    Breakdown: Name={best_metrics['breakdown']['name']:.2f}, "
              f"Specs={best_metrics['breakdown']['specs']:.2f}, "
              f"Color={best_metrics['breakdown']['color']:.2f}, "
              f"Price={best_metrics['breakdown']['price']:.2f}")

        return {"best_config": (best_model, best_prompt), "best_metrics": best_metrics}


async def main():
    print("\n" + "=" * 100)
    print(f"{Colors.BOLD}M5 IMPROVED MULTI-LEVER OPTIMIZATION{Colors.RESET}")
    print("=" * 100)

    print(f"\n{Colors.BOLD}Improvements:{Colors.RESET}")
    print(f"  • Testing proven models (mistral:7b, llama3.2:3b scored 0.958, 0.940 earlier)")
    print(f"  • More samples (15 per config for statistical significance)")
    print(f"  • Improved prompt strategies")
    print(f"  • Debug output to see actual extractions")

    # Get available models
    import subprocess
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    available_models = []
    for line in result.stdout.split("\n")[1:]:
        if line.strip():
            model_name = line.split()[0]
            if model_name:
                available_models.append(model_name)

    # Select the models that performed well before
    preferred = ["mistral:7b", "llama3.2:3b", "qwen2.5:32b", "llama3.1:8b"]
    models_to_test = [m for m in preferred if m in available_models][:4]

    if not models_to_test:
        models_to_test = available_models[:4]

    print(f"\n{Colors.BOLD}Selected Models:{Colors.RESET}")
    for model in models_to_test:
        print(f"  • {model}")

    print(f"\n{Colors.YELLOW}⚠️  Testing {len(models_to_test)} models * {len(PROMPT_STRATEGIES)} prompts * 5 samples = {len(models_to_test) * len(PROMPT_STRATEGIES) * 5} tests{Colors.RESET}")

    client = OllamaClient()
    optimizer = ImprovedMultiLeverOptimizer(client)

    await optimizer.grid_search(
        models=models_to_test,
        prompt_keys=list(PROMPT_STRATEGIES.keys()),
        num_samples=5  # 5 samples = 1 of each test case
    )

    optimizer.show_debug_samples()
    analysis = optimizer.analyze_results()

    await client.close()

    print("\n" + "=" * 100)
    print(f"{Colors.GREEN}{Colors.BOLD}✓ IMPROVED OPTIMIZATION COMPLETE{Colors.RESET}")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

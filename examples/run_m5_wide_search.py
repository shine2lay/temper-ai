#!/usr/bin/env python3
"""
M5 Wide Search Space Optimization - Comprehensive Model * Prompt * Temperature Grid

Wide search space:
- 8+ models (small, medium, large)
- 7 prompt strategies
- 3 temperature settings (optional 3rd lever)
- Real-time progress logging
- ETA estimation
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

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

# Test cases
TEST_CASES = [
    {"text": "MacBook Pro 16-inch M3 Max chip 36GB unified memory 1TB SSD storage Space Black $3499.99", "expected": {"name": "MacBook Pro 16-inch", "specs": "M3 Max, 36GB memory, 1TB SSD", "color": "Space Black", "price": 3499.99}},
    {"text": "Sony WH1000XM5 wireless noise canceling over-ear headphones black thirty-hour battery life three hundred ninety nine dollars", "expected": {"name": "Sony WH-1000XM5", "specs": "wireless, noise canceling, 30h battery", "color": "black", "price": 399.0}},
    {"text": "65\" Samsung QLED Smart TV QN90C with Neo Quantum HDR+, originally $2,199 now on sale for 1899 USD", "expected": {"name": "Samsung 65-inch QLED Smart TV QN90C", "specs": "Neo Quantum HDR+, Smart TV", "color": None, "price": 1899.0}},
    {"text": "Dyson V15 Detect Cordless Vacuum - Features: HEPA filtration, laser dust detection - Color: Yellow/Nickel - MSRP $649.99", "expected": {"name": "Dyson V15 Detect", "specs": "Cordless, HEPA, laser dust detection", "color": "Yellow", "price": 649.99}},
    {"text": "Apple Watch Series 9 GPS, case size: 45mm, Midnight Aluminum Case with matching Sport Band, retail price four hundred twenty-nine dollars", "expected": {"name": "Apple Watch Series 9", "specs": "GPS, 45mm", "color": "Midnight Aluminum", "price": 429.0}},
]

# Expanded prompt strategies
PROMPT_STRATEGIES = {
    "v1_baseline": {
        "name": "V1: Baseline",
        "template": """Extract product information from the following text and return ONLY a JSON object with these exact fields:
- name: product name (string)
- specs: key specifications (string)
- color: product color (string or null)
- price: numeric price in dollars (number)

Text: {text}

JSON:"""
    },

    "v2_strict": {
        "name": "V2: Strict Format",
        "template": """Extract as JSON. Required format: {{"name": "string", "specs": "string", "color": "string or null", "price": number}}

Rules:
- specs is comma-separated string, NOT nested object
- price is numeric, convert text numbers
- Use current/sale price if multiple

Text: {text}

JSON output:"""
    },

    "v3_few_shot": {
        "name": "V3: Few-Shot Examples",
        "template": """Extract product info as JSON.

Example 1:
Input: "iPhone 15 Pro 256GB Blue $999"
Output: {{"name": "iPhone 15 Pro", "specs": "256GB", "color": "Blue", "price": 999.0}}

Example 2:
Input: "Sony TV, fifty-five inch 4K, two thousand dollars"
Output: {{"name": "Sony 55-inch TV", "specs": "4K", "color": null, "price": 2000.0}}

Now extract:
Input: {text}
Output:"""
    },

    "v4_numbered_steps": {
        "name": "V4: Numbered Steps",
        "template": """Follow these steps:

1. Identify product name
2. List key specs as comma-separated string
3. Find color (or null)
4. Extract price as number (convert words to digits)

Text: {text}

Output JSON with fields: name, specs, color, price
JSON:"""
    },

    "v5_ultra_minimal": {
        "name": "V5: Ultra Minimal",
        "template": """Extract: name, specs, color, price.

Text: {text}

JSON:"""
    },

    "v6_conversational": {
        "name": "V6: Conversational",
        "template": """Hey! I need you to extract some product info from this text.

Can you give me:
- The product name
- Key specs (as a simple string, not fancy nested stuff)
- Color if mentioned (otherwise null)
- Price in dollars (as a number, and convert text like "five hundred" to 500)

Here's the text: {text}

Just give me back JSON with those 4 fields. Thanks!"""
    },

    "v7_technical": {
        "name": "V7: Technical/Precise",
        "template": """SYSTEM: JSON extraction module. Parse input and emit structured output.

SCHEMA:
- name: string (product identifier)
- specs: string (technical specifications, comma-delimited)
- color: string | null (appearance descriptor)
- price: float (USD denomination, numeric only)

CONSTRAINTS:
- specs field MUST be scalar string type
- Text numerals require lexical→numeric conversion
- Multiple prices: prioritize final/sale value

INPUT: {text}

OUTPUT:"""
    },
}

# Temperature settings (optional 3rd lever)
TEMPERATURE_SETTINGS = {
    "low": 0.1,
    "medium": 0.3,
    "high": 0.7,
}


class OllamaClient:
    def __init__(self, base_url="http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0)

    async def generate(self, model: str, prompt: str, temperature: float = 0.1) -> Tuple[str, Dict]:
        start_time = time.time()
        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": temperature}}
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
    def score(extracted: Optional[Dict], expected: Dict) -> float:
        if extracted is None:
            return 0.0

        name_score = QualityScorer._score_text(extracted.get("name", ""), expected["name"])
        specs_score = QualityScorer._score_text_fuzzy(extracted.get("specs", ""), expected["specs"])

        color_expected = expected.get("color")
        color_extracted = extracted.get("color")
        if color_expected is None:
            color_score = 1.0 if color_extracted is None else 0.5
        else:
            color_score = QualityScorer._score_text(color_extracted or "", color_expected)

        price_score = QualityScorer._score_price(extracted.get("price"), expected["price"])

        return name_score * 0.4 + specs_score * 0.3 + color_score * 0.1 + price_score * 0.2

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


class WideSearchOptimizer:
    def __init__(self, client: OllamaClient):
        self.client = client
        self.results_grid = {}
        self.start_time = None
        self.completed_configs = 0
        self.total_configs = 0

    async def test_configuration(self, model: str, prompt_key: str, temperature_key: str, config_num: int) -> Dict:
        prompt_strategy = PROMPT_STRATEGIES[prompt_key]
        temperature = TEMPERATURE_SETTINGS[temperature_key]
        results = []

        config_start = time.time()

        for test_case in TEST_CASES:
            prompt = prompt_strategy["template"].format(text=test_case["text"])
            response, metadata = await self.client.generate(model, prompt, temperature)

            extracted = QualityScorer.parse_json(response)
            quality = QualityScorer.score(extracted, test_case["expected"])

            results.append({
                "quality": quality,
                "duration": metadata["duration"],
                "success": metadata["success"],
            })

        avg_quality = sum(r["quality"] for r in results) / len(results)
        avg_duration = sum(r["duration"] for r in results if r["success"]) / max(1, sum(1 for r in results if r["success"]))
        success_rate = sum(1 for r in results if r["success"]) / len(results)

        config_duration = time.time() - config_start

        # Update progress
        self.completed_configs += 1
        elapsed = time.time() - self.start_time
        avg_time_per_config = elapsed / self.completed_configs
        remaining_configs = self.total_configs - self.completed_configs
        eta_seconds = avg_time_per_config * remaining_configs
        eta = datetime.now() + timedelta(seconds=eta_seconds)

        # Progress log
        progress_pct = (self.completed_configs / self.total_configs) * 100
        print(f"  [{self.completed_configs:>3d}/{self.total_configs}] "
              f"{progress_pct:>5.1f}% | "
              f"{model:<25s} + {PROMPT_STRATEGIES[prompt_key]['name'][:20]:<20s} + temp={temperature:.1f} | "
              f"Q={avg_quality:.3f} | "
              f"{config_duration:>4.1f}s | "
              f"ETA: {eta.strftime('%H:%M:%S')}")
        sys.stdout.flush()

        return {
            "model": model,
            "prompt": prompt_key,
            "temperature": temperature_key,
            "avg_quality": avg_quality,
            "avg_duration": avg_duration,
            "success_rate": success_rate,
            "num_samples": len(results),
        }

    async def wide_search(self, models: List[str], prompt_keys: List[str], temperature_keys: List[str]) -> Dict:
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}WIDE SEARCH SPACE OPTIMIZATION{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        print(f"  {Colors.BOLD}Search Space:{Colors.RESET}")
        print(f"    Models:       {len(models)}")
        for model in models:
            print(f"      • {model}")
        print(f"\n    Prompts:      {len(prompt_keys)}")
        for key in prompt_keys:
            print(f"      • {PROMPT_STRATEGIES[key]['name']}")
        print(f"\n    Temperatures: {len(temperature_keys)}")
        for key in temperature_keys:
            print(f"      • {key} (T={TEMPERATURE_SETTINGS[key]})")

        self.total_configs = len(models) * len(prompt_keys) * len(temperature_keys)
        total_tests = self.total_configs * len(TEST_CASES)

        print(f"\n    {Colors.YELLOW}Total Configurations: {self.total_configs}{Colors.RESET}")
        print(f"    {Colors.YELLOW}Total Tests: {total_tests}{Colors.RESET}")

        # Estimate time
        estimated_per_test = 5  # seconds
        estimated_total = total_tests * estimated_per_test
        estimated_minutes = estimated_total / 60

        print(f"    {Colors.YELLOW}Estimated Time: ~{estimated_minutes:.0f} minutes{Colors.RESET}")

        print(f"\n  {Colors.BOLD}Progress:{Colors.RESET}")
        print("    [Num] %     | Model                     | Prompt                | Quality | Time  | ETA")
        print(f"    {'-' * 95}")

        self.start_time = time.time()
        self.completed_configs = 0

        # Run all configurations sequentially (for progress tracking)
        config_num = 0
        for model in models:
            for prompt_key in prompt_keys:
                for temperature_key in temperature_keys:
                    config_num += 1
                    result = await self.test_configuration(model, prompt_key, temperature_key, config_num)
                    self.results_grid[(model, prompt_key, temperature_key)] = result

        total_time = time.time() - self.start_time
        print(f"\n  {Colors.GREEN}✓ Wide search complete in {total_time/60:.1f} minutes{Colors.RESET}\n")

        return self.results_grid

    def analyze_results(self):
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}RESULTS ANALYSIS{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        # Best configuration
        best = max(self.results_grid.items(), key=lambda x: x[1]["avg_quality"])
        best_model, best_prompt, best_temp = best[0]
        best_metrics = best[1]

        print(f"  {Colors.BOLD}🏆 Best Configuration:{Colors.RESET}")
        print(f"    Model:       {Colors.GREEN}{best_model}{Colors.RESET}")
        print(f"    Prompt:      {Colors.GREEN}{PROMPT_STRATEGIES[best_prompt]['name']}{Colors.RESET}")
        print(f"    Temperature: {Colors.GREEN}{best_temp} (T={TEMPERATURE_SETTINGS[best_temp]}){Colors.RESET}")
        print(f"    Quality:     {Colors.GREEN}{best_metrics['avg_quality']:.3f}{Colors.RESET}")
        print(f"    Duration:    {best_metrics['avg_duration']:.2f}s")

        # Top 10 configurations
        print(f"\n  {Colors.BOLD}Top 10 Configurations:{Colors.RESET}\n")
        print(f"    {'Rank':<5s} {'Model':<25s} {'Prompt':<25s} {'Temp':<10s} {'Quality':>10s}")
        print(f"    {'-' * 80}")

        top_configs = sorted(self.results_grid.items(), key=lambda x: x[1]["avg_quality"], reverse=True)[:10]
        for i, (config, metrics) in enumerate(top_configs, 1):
            model, prompt, temp = config
            quality_color = Colors.GREEN if metrics["avg_quality"] >= 0.90 else Colors.YELLOW if metrics["avg_quality"] >= 0.80 else Colors.RESET
            print(f"    {i:<5d} {model:<25s} {PROMPT_STRATEGIES[prompt]['name'][:24]:<25s} {temp:<10s} {quality_color}{metrics['avg_quality']:>10.3f}{Colors.RESET}")

        # Best per model
        print(f"\n  {Colors.BOLD}Best Configuration per Model:{Colors.RESET}\n")
        best_per_model = {}
        for (model, prompt, temp), metrics in self.results_grid.items():
            if model not in best_per_model or metrics["avg_quality"] > best_per_model[model]["quality"]:
                best_per_model[model] = {"prompt": prompt, "temp": temp, "quality": metrics["avg_quality"]}

        for model in sorted(best_per_model.keys()):
            info = best_per_model[model]
            print(f"    {model:<30s}: {PROMPT_STRATEGIES[info['prompt']]['name'][:30]:<30s} T={TEMPERATURE_SETTINGS[info['temp']]:.1f} → {info['quality']:.3f}")

        # Temperature analysis
        print(f"\n  {Colors.BOLD}Temperature Impact:{Colors.RESET}")
        temp_avg = {}
        for (model, prompt, temp), metrics in self.results_grid.items():
            if temp not in temp_avg:
                temp_avg[temp] = []
            temp_avg[temp].append(metrics["avg_quality"])

        for temp in sorted(temp_avg.keys()):
            avg_quality = sum(temp_avg[temp]) / len(temp_avg[temp])
            print(f"    {temp:<10s} (T={TEMPERATURE_SETTINGS[temp]:.1f}): avg quality = {avg_quality:.3f}")


async def main():
    print("\n" + "=" * 100)
    print(f"{Colors.BOLD}M5 WIDE SEARCH SPACE OPTIMIZATION - Model * Prompt * Temperature{Colors.RESET}")
    print("=" * 100)

    # Get available models
    import subprocess
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    available_models = []
    for line in result.stdout.split("\n")[1:]:
        if line.strip():
            model_name = line.split()[0]
            if model_name:
                available_models.append(model_name)

    # Select diverse models - prioritize those that performed well
    preferred = ["mistral:7b", "llama3.2:3b", "qwen2.5:32b", "llama3.1:8b", "qwen2.5:7b", "phi3:mini"]
    models_to_test = [m for m in preferred if m in available_models]

    # Add a few more if available
    for model in available_models:
        if model not in models_to_test and len(models_to_test) < 8:
            models_to_test.append(model)

    models_to_test = models_to_test[:8]  # Cap at 8

    print(f"\n{Colors.BOLD}Selected Configuration:{Colors.RESET}")
    print(f"  Models: {len(models_to_test)}")
    print(f"  Prompts: {len(PROMPT_STRATEGIES)}")
    print(f"  Temperatures: {len(TEMPERATURE_SETTINGS)}")
    print(f"  Total Configurations: {len(models_to_test) * len(PROMPT_STRATEGIES) * len(TEMPERATURE_SETTINGS)}")

    client = OllamaClient()
    optimizer = WideSearchOptimizer(client)

    await optimizer.wide_search(
        models=models_to_test,
        prompt_keys=list(PROMPT_STRATEGIES.keys()),
        temperature_keys=list(TEMPERATURE_SETTINGS.keys())
    )

    optimizer.analyze_results()

    await client.close()

    print("\n" + "=" * 100)
    print(f"{Colors.GREEN}{Colors.BOLD}✓ WIDE SEARCH OPTIMIZATION COMPLETE{Colors.RESET}")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

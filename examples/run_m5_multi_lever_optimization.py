#!/usr/bin/env python3
"""
M5 Multi-Lever Optimization - Model * Prompt Grid Search

Demonstrates M5 self-improvement with 2 optimization levers:
  1. LLM Model Selection (llama3.1:8b, qwen2.5:32b, mistral:7b, etc.)
  2. Prompt Engineering (minimal, detailed, few-shot, structured)

This is a realistic production scenario where multiple parameters
need to be optimized simultaneously.
"""

import asyncio
import json
import time
from collections import defaultdict
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
    {
        "text": "iPhone 15 Pro Max 256GB Natural Titanium $1199.00",
        "expected": {"name": "iPhone 15 Pro Max", "specs": "256GB", "color": "Natural Titanium", "price": 1199.00},
        "difficulty": "SIMPLE"
    },
    {
        "text": "Sony 65 inch 4K TV model XR-65A95K OLED display with 120Hz refresh rate originally two thousand four hundred ninety nine dollars",
        "expected": {"name": "Sony 65-inch 4K TV XR-65A95K", "specs": "OLED, 120Hz", "color": None, "price": 2499.00},
        "difficulty": "MEDIUM"
    },
    {
        "text": "The new MacBook comes with M3 Pro chip and 14-inch display. Memory is 18 gigabytes. Storage is 512 gigs. Space black costs $1999.",
        "expected": {"name": "MacBook Pro 14-inch", "specs": "M3 Pro, 18GB, 512GB", "color": "Space Black", "price": 1999.00},
        "difficulty": "COMPLEX"
    },
    {
        "text": "Samsung fridge bundle: 28 cu ft French door (fingerprint resistant stainless) for $2799, plus dishwasher $849. Fridge specs: dual cooling, ice maker.",
        "expected": {"name": "Samsung French Door Refrigerator", "specs": "28 cu ft, dual cooling, ice maker", "color": "Stainless Steel", "price": 2799.00},
        "difficulty": "V.COMPLEX"
    },
    {
        "text": "Canon EOS R5 camera (matte black corpo, not glossy) 45MP sensor, 8K video, IBIS stabilization. USD price: $3899 (Europe €3599). Includes two batteries.",
        "expected": {"name": "Canon EOS R5", "specs": "45MP, 8K video, IBIS", "color": "Matte Black", "price": 3899.00},
        "difficulty": "EXTREME"
    },
]

# Prompt strategies to test
PROMPT_STRATEGIES = {
    "minimal": {
        "name": "Minimal",
        "description": "Bare minimum instructions",
        "template": """Extract: name, specs, color, price (USD).

Text: {text}

JSON:"""
    },

    "detailed": {
        "name": "Detailed Instructions",
        "description": "Clear, explicit instructions with format requirements",
        "template": """Extract product information from the following text and return ONLY a JSON object with these exact fields:
- name: product name (string)
- specs: key specifications (string, not an object or array)
- color: product color (string or null if not mentioned)
- price: numeric price in dollars (number)

IMPORTANT:
- Use simple strings for name, specs, and color
- Do NOT use nested objects, arrays, or sets
- Convert text numbers to numeric format (e.g., "two thousand" → 2000)
- If multiple prices, extract the most relevant one

Text: {text}

Return only the JSON object with no markdown formatting:"""
    },

    "few_shot": {
        "name": "Few-Shot Examples",
        "description": "Includes examples to guide the model",
        "template": """Extract product info as JSON: name, specs, color, price.

Example 1:
Text: "Apple Watch Series 9 GPS 45mm Space Gray $429"
Output: {{"name": "Apple Watch Series 9", "specs": "GPS, 45mm", "color": "Space Gray", "price": 429.0}}

Example 2:
Text: "Gaming laptop with RTX 4080, thirty-two gigs RAM, black, two thousand dollars"
Output: {{"name": "Gaming Laptop", "specs": "RTX 4080, 32GB RAM", "color": "black", "price": 2000.0}}

Now extract from this text:
Text: {text}

Output:"""
    },

    "structured": {
        "name": "Structured Chain-of-Thought",
        "description": "Breaks down the extraction into steps",
        "template": """Extract product information step by step:

Text: {text}

Step 1: Identify the product name
Step 2: Extract key specifications
Step 3: Determine the color (or null)
Step 4: Find the price in USD

Now output as JSON with fields: name, specs, color, price

JSON:"""
    },
}


class OllamaClient:
    """Async client for Ollama API."""

    def __init__(self, base_url="http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0)

    async def generate(self, model: str, prompt: str) -> Tuple[str, Dict]:
        """Generate response from model."""
        start_time = time.time()

        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1}
                }
            )
            response.raise_for_status()
            result = response.json()

            duration = time.time() - start_time

            metadata = {
                "duration": duration,
                "tokens": result.get("eval_count", 0) + result.get("prompt_eval_count", 0),
                "success": True,
            }

            return result.get("response", ""), metadata

        except Exception as e:
            return "", {"duration": 0, "tokens": 0, "success": False, "error": str(e)}

    async def close(self):
        await self.client.aclose()


class QualityScorer:
    """Score extraction quality."""

    @staticmethod
    def parse_json(response: str) -> Optional[Dict]:
        """Extract JSON from response."""
        try:
            response = response.strip()

            # Strip markdown code blocks
            if response.startswith("```"):
                lines = response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = "\n".join(lines)

            # Find JSON
            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start == -1 or json_end == 0:
                return None

            json_str = response[json_start:json_end]

            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # Try to fix common issues
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
        """Score extraction quality (0.0-1.0)."""
        if extracted is None:
            return 0.0

        # Name (40%)
        name_score = QualityScorer._score_text(
            extracted.get("name", ""), expected["name"]
        )

        # Specs (30%)
        specs_score = QualityScorer._score_text_fuzzy(
            extracted.get("specs", ""), expected["specs"]
        )

        # Color (10%)
        color_expected = expected.get("color")
        color_extracted = extracted.get("color")
        if color_expected is None:
            color_score = 1.0 if color_extracted is None else 0.5
        else:
            color_score = QualityScorer._score_text(color_extracted or "", color_expected)

        # Price (20%)
        price_score = QualityScorer._score_price(
            extracted.get("price"), expected["price"]
        )

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


class M5MultiLeverOptimizer:
    """Optimizes both model and prompt simultaneously."""

    def __init__(self, client: OllamaClient):
        self.client = client
        self.results_grid = {}  # (model, prompt) -> metrics

    async def test_configuration(
        self,
        model: str,
        prompt_key: str,
        num_samples: int = 10
    ) -> Dict:
        """Test a specific (model, prompt) configuration."""

        prompt_strategy = PROMPT_STRATEGIES[prompt_key]
        results = []

        for test_case in TEST_CASES[:num_samples]:
            # Format prompt with strategy
            prompt = prompt_strategy["template"].format(text=test_case["text"])

            # Generate
            response, metadata = await self.client.generate(model, prompt)

            # Score
            extracted = QualityScorer.parse_json(response)
            quality = QualityScorer.score(extracted, test_case["expected"])

            results.append({
                "quality": quality,
                "duration": metadata["duration"],
                "success": metadata["success"],
                "difficulty": test_case["difficulty"],
            })

        # Calculate metrics
        avg_quality = sum(r["quality"] for r in results) / len(results)
        avg_duration = sum(r["duration"] for r in results if r["success"]) / max(1, sum(1 for r in results if r["success"]))
        success_rate = sum(1 for r in results if r["success"]) / len(results)

        return {
            "model": model,
            "prompt": prompt_key,
            "avg_quality": avg_quality,
            "avg_duration": avg_duration,
            "success_rate": success_rate,
            "num_samples": len(results),
        }

    async def grid_search(
        self,
        models: List[str],
        prompt_keys: List[str],
        num_samples: int = 5
    ) -> Dict:
        """Run grid search over (model * prompt) space."""

        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}GRID SEARCH: MODEL * PROMPT OPTIMIZATION{Colors.RESET}")
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

        print(f"\n  {Colors.YELLOW}⚠️  Running {len(models) * len(prompt_keys)} configurations...{Colors.RESET}\n")

        # Test all configurations
        tasks = []
        configs = []

        for model in models:
            for prompt_key in prompt_keys:
                tasks.append(self.test_configuration(model, prompt_key, num_samples))
                configs.append((model, prompt_key))

        results = await asyncio.gather(*tasks)

        # Store in grid
        for i, (model, prompt_key) in enumerate(configs):
            self.results_grid[(model, prompt_key)] = results[i]

        print(f"  {Colors.GREEN}✓ Grid search complete{Colors.RESET}\n")

        return self.results_grid

    def analyze_results(self) -> Dict:
        """Analyze grid search results."""

        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}RESULTS ANALYSIS{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        # Find best configuration
        best_config = max(
            self.results_grid.items(),
            key=lambda x: x[1]["avg_quality"]
        )
        best_model, best_prompt = best_config[0]
        best_metrics = best_config[1]

        # Find best per model
        best_per_model = {}
        for (model, prompt), metrics in self.results_grid.items():
            if model not in best_per_model or metrics["avg_quality"] > best_per_model[model]["quality"]:
                best_per_model[model] = {
                    "prompt": prompt,
                    "quality": metrics["avg_quality"],
                    "duration": metrics["avg_duration"],
                }

        # Find best per prompt
        best_per_prompt = {}
        for (model, prompt), metrics in self.results_grid.items():
            if prompt not in best_per_prompt or metrics["avg_quality"] > best_per_prompt[prompt]["quality"]:
                best_per_prompt[prompt] = {
                    "model": model,
                    "quality": metrics["avg_quality"],
                    "duration": metrics["avg_duration"],
                }

        # Display results grid
        print(f"  {Colors.BOLD}Quality Grid (higher is better):{Colors.RESET}\n")

        # Get unique models and prompts
        models = sorted(set(model for model, _ in self.results_grid.keys()))
        prompts = sorted(set(prompt for _, prompt in self.results_grid.keys()))

        # Header
        print(f"    {'Model':<30s}", end="")
        for prompt in prompts:
            prompt_name = PROMPT_STRATEGIES[prompt]["name"][:12]
            print(f" {prompt_name:>12s}", end="")
        print()
        print(f"    {'-' * (30 + 13 * len(prompts))}")

        # Rows
        for model in models:
            print(f"    {model:<30s}", end="")
            for prompt in prompts:
                if (model, prompt) in self.results_grid:
                    quality = self.results_grid[(model, prompt)]["avg_quality"]

                    # Highlight best
                    if model == best_model and prompt == best_prompt:
                        print(f" {Colors.GREEN}{Colors.BOLD}{quality:>12.3f}{Colors.RESET}", end="")
                    elif quality >= 0.85:
                        print(f" {Colors.GREEN}{quality:>12.3f}{Colors.RESET}", end="")
                    elif quality >= 0.75:
                        print(f" {Colors.YELLOW}{quality:>12.3f}{Colors.RESET}", end="")
                    else:
                        print(f" {Colors.RED}{quality:>12.3f}{Colors.RESET}", end="")
                else:
                    print(f" {'N/A':>12s}", end="")
            print()

        # Best configuration
        print(f"\n  {Colors.BOLD}🏆 Best Configuration:{Colors.RESET}")
        print(f"    Model:   {Colors.GREEN}{best_model}{Colors.RESET}")
        print(f"    Prompt:  {Colors.GREEN}{PROMPT_STRATEGIES[best_prompt]['name']}{Colors.RESET}")
        print(f"    Quality: {Colors.GREEN}{best_metrics['avg_quality']:.3f}{Colors.RESET}")
        print(f"    Speed:   {best_metrics['avg_duration']:.2f}s")

        # Best per model
        print(f"\n  {Colors.BOLD}Best Prompt for Each Model:{Colors.RESET}")
        for model in sorted(best_per_model.keys()):
            info = best_per_model[model]
            prompt_name = PROMPT_STRATEGIES[info['prompt']]['name']
            print(f"    {model:<30s}: {prompt_name:<25s} (Q:{info['quality']:.3f})")

        # Best per prompt
        print(f"\n  {Colors.BOLD}Best Model for Each Prompt:{Colors.RESET}")
        for prompt in sorted(best_per_prompt.keys()):
            info = best_per_prompt[prompt]
            prompt_name = PROMPT_STRATEGIES[prompt]['name']
            print(f"    {prompt_name:<25s}: {info['model']:<30s} (Q:{info['quality']:.3f})")

        # Insights
        print(f"\n  {Colors.BOLD}Key Insights:{Colors.RESET}")

        # Which prompt strategy works best overall?
        prompt_avg_quality = defaultdict(list)
        for (model, prompt), metrics in self.results_grid.items():
            prompt_avg_quality[prompt].append(metrics["avg_quality"])

        best_prompt_overall = max(
            prompt_avg_quality.items(),
            key=lambda x: sum(x[1]) / len(x[1])
        )
        print(f"    • Best prompt strategy overall: {Colors.GREEN}{PROMPT_STRATEGIES[best_prompt_overall[0]]['name']}{Colors.RESET}")
        print(f"      Avg quality across models: {sum(best_prompt_overall[1])/len(best_prompt_overall[1]):.3f}")

        # Which model is most consistent across prompts?
        model_variance = {}
        for model in models:
            qualities = [
                self.results_grid[(model, prompt)]["avg_quality"]
                for prompt in prompts
                if (model, prompt) in self.results_grid
            ]
            if qualities:
                variance = max(qualities) - min(qualities)
                model_variance[model] = variance

        most_consistent = min(model_variance.items(), key=lambda x: x[1])
        print(f"    • Most consistent model: {Colors.GREEN}{most_consistent[0]}{Colors.RESET}")
        print(f"      Quality variance: {most_consistent[1]:.3f}")

        # Prompt sensitivity
        model_prompt_sensitivity = {}
        for model in models:
            qualities = [
                self.results_grid[(model, prompt)]["avg_quality"]
                for prompt in prompts
                if (model, prompt) in self.results_grid
            ]
            if qualities:
                sensitivity = max(qualities) - min(qualities)
                model_prompt_sensitivity[model] = sensitivity

        most_sensitive = max(model_prompt_sensitivity.items(), key=lambda x: x[1])
        print(f"    • Most prompt-sensitive model: {Colors.YELLOW}{most_sensitive[0]}{Colors.RESET}")
        print(f"      Quality range: {most_sensitive[1]:.3f} (prompt engineering critical!)")

        return {
            "best_config": (best_model, best_prompt),
            "best_metrics": best_metrics,
            "best_per_model": best_per_model,
            "best_per_prompt": best_per_prompt,
        }


async def main():
    print("\n" + "=" * 100)
    print(f"{Colors.BOLD}M5 MULTI-LEVER OPTIMIZATION - Model * Prompt Grid Search{Colors.RESET}")
    print("=" * 100)

    print(f"\n{Colors.BOLD}Optimization Levers:{Colors.RESET}")
    print("  1. LLM Model Selection")
    print("  2. Prompt Engineering Strategy")

    print(f"\n{Colors.BOLD}Prompt Strategies:{Colors.RESET}")
    for key, strategy in PROMPT_STRATEGIES.items():
        print(f"  • {strategy['name']:<30s}: {strategy['description']}")

    # Select models to test
    import subprocess
    result = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True
    )

    available_models = []
    for line in result.stdout.split("\n")[1:]:
        if line.strip():
            model_name = line.split()[0]
            if model_name:
                available_models.append(model_name)

    # Select diverse set of models
    models_to_test = []

    # Small model
    small = [m for m in available_models if any(s in m for s in ["3b", "2b", "mini"])]
    if small:
        models_to_test.append(small[0])

    # Medium models
    medium = [m for m in available_models if any(s in m for s in ["7b", "8b"])]
    if medium:
        models_to_test.extend(medium[:2])

    # Large model
    large = [m for m in available_models if any(s in m for s in ["32b", "20b"])]
    if large:
        models_to_test.append(large[0])

    # Remove duplicates
    models_to_test = list(dict.fromkeys(models_to_test))[:4]

    print(f"\n{Colors.BOLD}Selected Models:{Colors.RESET}")
    for model in models_to_test:
        print(f"  • {model}")

    print(f"\n{Colors.YELLOW}⚠️  This will test {len(models_to_test)} models * {len(PROMPT_STRATEGIES)} prompts = {len(models_to_test) * len(PROMPT_STRATEGIES)} configurations{Colors.RESET}")
    print(f"{Colors.YELLOW}⚠️  Estimated time: 10-15 minutes{Colors.RESET}")

    # Initialize
    client = OllamaClient()
    optimizer = M5MultiLeverOptimizer(client)

    # Run grid search
    await optimizer.grid_search(
        models=models_to_test,
        prompt_keys=list(PROMPT_STRATEGIES.keys()),
        num_samples=5
    )

    # Analyze results
    analysis = optimizer.analyze_results()

    await client.close()

    print("\n" + "=" * 100)
    print(f"{Colors.GREEN}{Colors.BOLD}✓ MULTI-LEVER OPTIMIZATION COMPLETE{Colors.RESET}")
    print("=" * 100 + "\n")

    print(f"{Colors.BOLD}Recommendation:{Colors.RESET}")
    best_model, best_prompt = analysis["best_config"]
    print(f"  Deploy: {Colors.GREEN}{best_model}{Colors.RESET}")
    print(f"  With:   {Colors.GREEN}{PROMPT_STRATEGIES[best_prompt]['name']}{Colors.RESET}")
    print(f"  Quality: {Colors.GREEN}{analysis['best_metrics']['avg_quality']:.3f}{Colors.RESET}")
    print()


if __name__ == "__main__":
    asyncio.run(main())

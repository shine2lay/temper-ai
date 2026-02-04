#!/usr/bin/env python3
"""
M5 Complexity Stress Test - Find where models break down

Tests models across 5 complexity levels:
1. SIMPLE - straightforward extraction
2. MEDIUM - unit conversions, multiple formats
3. COMPLEX - ambiguous wording, text-encoded numbers
4. VERY_COMPLEX - bundles, promotions, multiple products
5. EXTREME - conflicting info, typos, multi-language
"""

import asyncio
import json
import time
from datetime import datetime
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
    MAGENTA = '\033[95m'

# Complexity levels with test cases
COMPLEXITY_TESTS = {
    "SIMPLE": [
        {
            "raw_text": "iPhone 15 Pro Max 256GB Natural Titanium $1199.00",
            "expected": {
                "name": "iPhone 15 Pro Max",
                "specs": "256GB",
                "color": "Natural Titanium",
                "price": 1199.00,
            }
        },
        {
            "raw_text": "Dell XPS 13 laptop, Intel i7, 16GB RAM, 512GB SSD, Silver, Price: $1,299",
            "expected": {
                "name": "Dell XPS 13",
                "specs": "Intel i7, 16GB RAM, 512GB SSD",
                "color": "Silver",
                "price": 1299.00,
            }
        },
    ],
    "MEDIUM": [
        {
            "raw_text": "Sony 65 inch 4K TV model XR-65A95K OLED display with 120Hz refresh rate originally two thousand four hundred ninety nine dollars now on sale",
            "expected": {
                "name": "Sony 65-inch 4K TV XR-65A95K",
                "specs": "OLED, 120Hz",
                "color": None,
                "price": 2499.00,  # Ignore "on sale" mention, extract original
            }
        },
        {
            "raw_text": "Gaming laptop: ASUS ROG Strix with RTX 4080 (16 gigs VRAM), 32 gigabytes DDR5, 2TB NVMe, Eclipse Gray, retail pricing at $2899.99",
            "expected": {
                "name": "ASUS ROG Strix",
                "specs": "RTX 4080, 32GB DDR5, 2TB NVMe",
                "color": "Eclipse Gray",
                "price": 2899.99,
            }
        },
    ],
    "COMPLEX": [
        {
            "raw_text": "The new MacBook comes with their M3 chip (it's the Pro variant, not the base one) and has a gorgeous 14-inch liquid retina display. Memory is 18 gigabytes unified. Storage is 512 gigs. Available in space black or silver. The space black one costs $1999 while the silver is $1949.",
            "expected": {
                "name": "MacBook Pro 14-inch",
                "specs": "M3 Pro, 18GB, 512GB",
                "color": "Space Black",
                "price": 1999.00,  # Higher price variant
            }
        },
        {
            "raw_text": "Espresso machine: Breville Barista Express with built-in grinder, 15-bar Italian pump, comes in stainless steel (most popular) or black truffle. Dimensions: 13\" x 12\" x 16\". Wattage: 1600W. MSRP is $699.95 but currently $599.95 after rebate",
            "expected": {
                "name": "Breville Barista Express",
                "specs": "15-bar pump, built-in grinder, 1600W",
                "color": "Stainless Steel",
                "price": 699.95,  # MSRP, not sale price
            }
        },
    ],
    "VERY_COMPLEX": [
        {
            "raw_text": "Bundle deal on Samsung appliances: French door refrigerator (28 cu ft, fingerprint resistant stainless), dishwasher (42 dBA quiet), and range (5.8 cu ft oven). Fridge alone is $2799, dishwasher $849, range $1199. Bundle price is $4299 (save $548). All in stainless steel finish.",
            "expected": {
                "name": "Samsung French Door Refrigerator",
                "specs": "28 cu ft, fingerprint resistant",
                "color": "Stainless Steel",
                "price": 2799.00,  # Individual fridge price, not bundle
            }
        },
        {
            "raw_text": "DJI Mavic 3 Pro drone package includes: drone with 3 cameras (Hasselblad main + dual tele), 6x batteries (extended flight kit), RC Pro controller, carrying case, ND filters set, 1TB SSD, and Care Refresh warranty. Drone body MSRP: $2199. Controller: $1199. Full package: $3999 (limited time offer ends Dec 31). Cinefoil Gray color.",
            "expected": {
                "name": "DJI Mavic 3 Pro",
                "specs": "3 cameras, Hasselblad",
                "color": "Cinefoil Gray",
                "price": 2199.00,  # Drone body price only
            }
        },
    ],
    "EXTREME": [
        {
            "raw_text": "Nouveau caméra Canon EOS R5 (corpo est noir mat, pas le noir brillant) avec capteur plein format 45MP, vidéo 8K, stabilisation IBIS. Le prix en USD est $3899 (or €3599 in Europe, ¥589000 in Japan). Includes deux batteries LP-E6NH, chargeur mural AC, câble USB-C (pas Micro-USB!), courroie de cou. Poids: approximately 1.62 lbs or 738g pour le corpo seul.",
            "expected": {
                "name": "Canon EOS R5",
                "specs": "45MP full frame, 8K video, IBIS",
                "color": "Matte Black",
                "price": 3899.00,  # USD price
            }
        },
        {
            "raw_text": "**CLEARANCE** - Refurbished Microsoft Surface Pro 8 (was $1499, then marked to $999, now FINAL PRICE) 2-in-1 detachable laptop/tablet hybrid running Windows 11 Pro NOT Home edition, featuring: Intel Core i5-1135G7 (11th generation, 4 cores/8 threads @ 2.4GHz base / up to 4.2GHz turbo), 8GB LPDDR4x memory (soldered, not upgradeable - NOTE: some units may have 16GB, check specifications), 256GB PCIe Gen3 NVMe SSD (replaceable m.2 2230 form factor), 13\" PixelSense touchscreen display @ 2880x1920 resolution (3:2 aspect ratio, 267 PPI, 120Hz refresh support), platinum (silver-ish) color, battery life: ~up to 16 hours (actual may vary), Type Cover keyboard SOLD SEPARATELY for additional $129.99. **AS-IS no returns accepted**",
            "expected": {
                "name": "Microsoft Surface Pro 8",
                "specs": "Intel Core i5-1135G7, 8GB RAM, 256GB SSD, 13-inch touchscreen",
                "color": "Platinum",
                "price": 999.00,  # Current price after markdowns
            }
        },
    ],
}

EXTRACTION_PROMPT = """Extract product information from the following text and return ONLY a JSON object with these exact fields:
- name: product name (string)
- specs: key specifications (string, not an object or array)
- color: product color (string or null if not mentioned)
- price: numeric price in dollars (number)

IMPORTANT:
- Use simple strings for name, specs, and color. Do NOT use nested objects, arrays, or sets.
- If multiple prices mentioned, extract the most relevant one (MSRP or current price)
- If multiple products in a bundle, extract the main product
- Convert text numbers to numeric format (e.g., "two thousand" → 2000)
- Ignore sale prices unless that's the only price given

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
            print(f"  {Colors.RED}HTTP Error with {model}: {e.response.status_code}{Colors.RESET}")
            return "", {"duration": 0, "tokens": 0, "error": "http_error", "error_detail": str(e)}
        except Exception as e:
            print(f"  {Colors.RED}Error with {model}: {type(e).__name__}{Colors.RESET}")
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
                lines = response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = "\n".join(lines)

            # Find JSON in response
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
                    raise

        except:
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


async def test_model_complexity(client: OllamaClient, model: str):
    """Test a model across all complexity levels."""
    results_by_level = {}

    for level, test_cases in COMPLEXITY_TESTS.items():
        level_results = []

        for test_case in test_cases:
            prompt = EXTRACTION_PROMPT.format(text=test_case["raw_text"])
            response, metadata = await client.generate(model, prompt)

            extracted = QualityScorer.parse_json(response)
            quality, score_breakdown = QualityScorer.score(extracted, test_case["expected"])

            level_results.append({
                "quality": quality,
                "duration": metadata["duration"],
                "tokens": metadata["tokens"],
                "extracted": extracted,
                "expected": test_case["expected"],
                "score_breakdown": score_breakdown,
                "has_error": "error" in metadata,
            })

        # Calculate average for this level
        avg_quality = sum(r["quality"] for r in level_results) / len(level_results)
        success_rate = sum(1 for r in level_results if r["quality"] >= 0.7) / len(level_results)

        results_by_level[level] = {
            "avg_quality": avg_quality,
            "success_rate": success_rate,
            "results": level_results,
        }

    return {
        "model": model,
        "by_complexity": results_by_level,
    }


async def main():
    print("\n" + "=" * 100)
    print(f"{Colors.BOLD}M5 COMPLEXITY STRESS TEST - Find Model Breaking Points{Colors.RESET}")
    print("=" * 100)

    print(f"\n{Colors.BOLD}Test Configuration:{Colors.RESET}")
    print(f"  • Complexity Levels: 5 (SIMPLE → EXTREME)")
    print(f"  • Tests per level: 2")
    print(f"  • Total tests per model: 10")

    # Get available models
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

    print(f"\n{Colors.BOLD}Available Models ({len(available_models)}):{Colors.RESET}")

    # Categorize by size
    coding_models = [m for m in available_models if 'code' in m.lower() or 'wizard' in m.lower() or 'star' in m.lower()]
    small_models = [m for m in available_models if any(size in m for size in ['3b', '2b', '1.5b', 'mini'])]
    medium_models = [m for m in available_models if any(size in m for size in ['7b', '6.7b', '8b'])]
    large_models = [m for m in available_models if any(size in m for size in ['13b', '14b', '20b', '32b', '70b', '120b'])]

    print(f"\n  {Colors.CYAN}Small models (≤3B):{Colors.RESET} {len(small_models)}")
    for m in small_models[:5]:
        print(f"    • {m}")

    print(f"\n  {Colors.CYAN}Medium models (6-8B):{Colors.RESET} {len(medium_models)}")
    for m in medium_models[:5]:
        print(f"    • {m}")

    print(f"\n  {Colors.CYAN}Large models (≥13B):{Colors.RESET} {len(large_models)}")
    for m in large_models[:5]:
        print(f"    • {m}")

    print(f"\n  {Colors.CYAN}Coding models:{Colors.RESET} {len(coding_models)}")
    for m in coding_models[:5]:
        print(f"    • {m}")

    # Select models to test - focus on variety
    models_to_test = []
    models_to_test.extend(small_models[:3])      # 3 small
    models_to_test.extend(medium_models[:5])     # 5 medium
    models_to_test.extend(large_models[:3])      # 3 large
    models_to_test.extend(coding_models[:4])     # 4 coding
    models_to_test = list(dict.fromkeys(models_to_test))[:12]  # Remove duplicates, cap at 12

    print(f"\n{Colors.BOLD}Testing {len(models_to_test)} models:{Colors.RESET}")
    for model in models_to_test:
        print(f"  • {model}")

    print(f"\n{Colors.YELLOW}⚠️  This will make {len(models_to_test) * 10} real LLM calls (5-10 minutes){Colors.RESET}")
    print()

    # Run tests
    client = OllamaClient()

    print(f"{Colors.CYAN}{'─' * 100}{Colors.RESET}")
    print(f"{Colors.CYAN}{Colors.BOLD}RUNNING COMPLEXITY TESTS{Colors.RESET}")
    print(f"{Colors.CYAN}{'─' * 100}{Colors.RESET}\n")

    # Test all models in parallel
    tasks = [test_model_complexity(client, model) for model in models_to_test]
    all_results = await asyncio.gather(*tasks)

    await client.close()

    # Display results
    print(f"\n{Colors.CYAN}{'─' * 100}{Colors.RESET}")
    print(f"{Colors.BOLD}COMPLEXITY BREAKDOWN BY MODEL{Colors.RESET}")
    print(f"{Colors.CYAN}{'─' * 100}{Colors.RESET}\n")

    # Header
    print(f"{'Model':<30s} {'SIMPLE':>10s} {'MEDIUM':>10s} {'COMPLEX':>10s} {'V.COMPLEX':>10s} {'EXTREME':>10s} {'Break Point':>15s}")
    print("─" * 100)

    for result in all_results:
        model = result["model"]
        by_complexity = result["by_complexity"]

        # Get scores
        simple = by_complexity["SIMPLE"]["avg_quality"]
        medium = by_complexity["MEDIUM"]["avg_quality"]
        complex_score = by_complexity["COMPLEX"]["avg_quality"]
        very_complex = by_complexity["VERY_COMPLEX"]["avg_quality"]
        extreme = by_complexity["EXTREME"]["avg_quality"]

        # Determine break point (first level below 0.7)
        break_point = "None"
        if simple < 0.7:
            break_point = "SIMPLE"
        elif medium < 0.7:
            break_point = "MEDIUM"
        elif complex_score < 0.7:
            break_point = "COMPLEX"
        elif very_complex < 0.7:
            break_point = "V.COMPLEX"
        elif extreme < 0.7:
            break_point = "EXTREME"

        # Color code scores
        def color_score(score):
            if score >= 0.8:
                return f"{Colors.GREEN}{score:>10.3f}{Colors.RESET}"
            elif score >= 0.7:
                return f"{Colors.YELLOW}{score:>10.3f}{Colors.RESET}"
            else:
                return f"{Colors.RED}{score:>10.3f}{Colors.RESET}"

        print(f"{model:<30s} "
              f"{color_score(simple)} "
              f"{color_score(medium)} "
              f"{color_score(complex_score)} "
              f"{color_score(very_complex)} "
              f"{color_score(extreme)} "
              f"{break_point:>15s}")

    # Analysis
    print(f"\n{Colors.BOLD}Analysis:{Colors.RESET}\n")

    # Find most robust
    print(f"{Colors.BOLD}Most Robust Models (handle extreme complexity):{Colors.RESET}")
    robust = sorted(
        [(r["model"], r["by_complexity"]["EXTREME"]["avg_quality"]) for r in all_results],
        key=lambda x: x[1],
        reverse=True
    )[:3]
    for i, (model, score) in enumerate(robust, 1):
        print(f"  {i}. {model}: {score:.3f}")

    # Find early failures
    print(f"\n{Colors.BOLD}Models that Struggle Early:{Colors.RESET}")
    for result in all_results:
        simple_score = result["by_complexity"]["SIMPLE"]["avg_quality"]
        medium_score = result["by_complexity"]["MEDIUM"]["avg_quality"]
        if simple_score < 0.8 or medium_score < 0.7:
            print(f"  • {result['model']}: SIMPLE={simple_score:.3f}, MEDIUM={medium_score:.3f}")

    # Complexity degradation
    print(f"\n{Colors.BOLD}Complexity Degradation (SIMPLE → EXTREME):{Colors.RESET}")
    for result in all_results:
        simple = result["by_complexity"]["SIMPLE"]["avg_quality"]
        extreme = result["by_complexity"]["EXTREME"]["avg_quality"]
        degradation = simple - extreme
        if degradation > 0.2:
            print(f"  • {result['model']}: -{degradation:.3f} ({simple:.3f} → {extreme:.3f})")

    print("\n" + "=" * 100)
    print(f"{Colors.GREEN}{Colors.BOLD}✓ COMPLEXITY STRESS TEST COMPLETE{Colors.RESET}")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

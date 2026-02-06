#!/usr/bin/env python3
"""
M5 Real Self-Improvement Cycle with Ollama

Demonstrates the complete M5 self-improvement loop:
  DETECT → ANALYZE → STRATEGY → EXPERIMENT → DEPLOY → REPEAT

Uses real Ollama models and complexity-aware strategy.
This is the foundation for multi-agent workflows.
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

# Test cases covering all complexity levels
TEST_CASES = [
    # SIMPLE (30%)
    {
        "text": "iPhone 15 Pro Max 256GB Natural Titanium $1199.00",
        "expected": {"name": "iPhone 15 Pro Max", "specs": "256GB", "color": "Natural Titanium", "price": 1199.00},
        "difficulty": "SIMPLE"
    },
    {
        "text": "Dell XPS 13 laptop, Intel i7, 16GB RAM, 512GB SSD, Silver, Price: $1,299",
        "expected": {"name": "Dell XPS 13", "specs": "Intel i7, 16GB RAM, 512GB SSD", "color": "Silver", "price": 1299.00},
        "difficulty": "SIMPLE"
    },
    {
        "text": "Sony WH-1000XM5 wireless headphones, noise canceling, 30hr battery, black, $399",
        "expected": {"name": "Sony WH-1000XM5", "specs": "wireless, noise canceling, 30hr battery", "color": "black", "price": 399.00},
        "difficulty": "SIMPLE"
    },
    # MEDIUM (30%)
    {
        "text": "Sony 65 inch 4K TV model XR-65A95K OLED display with 120Hz refresh rate originally two thousand four hundred ninety nine dollars",
        "expected": {"name": "Sony 65-inch 4K TV XR-65A95K", "specs": "OLED, 120Hz", "color": None, "price": 2499.00},
        "difficulty": "MEDIUM"
    },
    {
        "text": "Gaming laptop: ASUS ROG Strix with RTX 4080 (16 gigs VRAM), 32 gigabytes DDR5, 2TB NVMe, Eclipse Gray, $2899.99",
        "expected": {"name": "ASUS ROG Strix", "specs": "RTX 4080, 32GB DDR5, 2TB NVMe", "color": "Eclipse Gray", "price": 2899.99},
        "difficulty": "MEDIUM"
    },
    {
        "text": "Espresso machine: Breville Barista Express, fifteen bar Italian pump, built-in grinder, stainless steel, MSRP $699.95",
        "expected": {"name": "Breville Barista Express", "specs": "15-bar pump, built-in grinder", "color": "Stainless Steel", "price": 699.95},
        "difficulty": "MEDIUM"
    },
    # COMPLEX (25%)
    {
        "text": "The new MacBook comes with M3 Pro chip and 14-inch display. Memory is 18 gigabytes. Storage is 512 gigs. Space black costs $1999.",
        "expected": {"name": "MacBook Pro 14-inch", "specs": "M3 Pro, 18GB, 512GB", "color": "Space Black", "price": 1999.00},
        "difficulty": "COMPLEX"
    },
    {
        "text": "DJI Mavic 3 Pro drone with Hasselblad camera, three cameras total, 46-minute flight time. Cinefoil Gray. Body only: $2199",
        "expected": {"name": "DJI Mavic 3 Pro", "specs": "Hasselblad, 3 cameras, 46min flight", "color": "Cinefoil Gray", "price": 2199.00},
        "difficulty": "COMPLEX"
    },
    # V.COMPLEX (10%)
    {
        "text": "Samsung fridge bundle: 28 cu ft French door (fingerprint resistant stainless) for $2799, plus dishwasher $849. Fridge specs: dual cooling, ice maker.",
        "expected": {"name": "Samsung French Door Refrigerator", "specs": "28 cu ft, dual cooling, ice maker", "color": "Stainless Steel", "price": 2799.00},
        "difficulty": "V.COMPLEX"
    },
    # EXTREME (5%)
    {
        "text": "Canon EOS R5 camera (matte black corpo, not glossy) 45MP sensor, 8K video, IBIS stabilization. USD price: $3899 (Europe €3599). Includes two batteries.",
        "expected": {"name": "Canon EOS R5", "specs": "45MP, 8K video, IBIS", "color": "Matte Black", "price": 3899.00},
        "difficulty": "EXTREME"
    },
]

EXTRACTION_PROMPT = """Extract product information from the following text and return ONLY a JSON object with these exact fields:
- name: product name (string)
- specs: key specifications (string, not an object or array)
- color: product color (string or null if not mentioned)
- price: numeric price in dollars (number)

IMPORTANT:
- Use simple strings for name, specs, and color. Do NOT use nested objects, arrays, or sets.
- Convert text numbers to numeric format (e.g., "two thousand" → 2000)
- If multiple prices, extract the most relevant one

Text: {text}

Return only the JSON object with no markdown formatting:"""


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


class M5SelfImprovementOrchestrator:
    """Orchestrates the M5 self-improvement cycle."""

    def __init__(self, client: OllamaClient):
        self.client = client
        self.cycle_history = []

        # Thresholds for optimization
        self.thresholds = {
            "quality": 0.85,      # Want quality ≥ 0.85
            "success_rate": 0.80,  # Want 80%+ success rate
        }

    async def run_baseline(self, model: str, num_samples: int = 20) -> Dict:
        """DETECT: Run baseline model and collect metrics."""
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}PHASE 1: DETECT - Running Baseline{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"\n  Model: {Colors.BOLD}{model}{Colors.RESET}")
        print(f"  Samples: {num_samples}")

        results = []
        by_difficulty = defaultdict(list)

        # Sample tests
        import random
        test_sample = random.sample(TEST_CASES, min(num_samples, len(TEST_CASES)))

        print(f"\n  Running {len(test_sample)} tests...")

        for i, test_case in enumerate(test_sample, 1):
            prompt = EXTRACTION_PROMPT.format(text=test_case["text"])
            response, metadata = await self.client.generate(model, prompt)

            extracted = QualityScorer.parse_json(response)
            quality = QualityScorer.score(extracted, test_case["expected"])

            results.append({
                "quality": quality,
                "duration": metadata["duration"],
                "success": metadata["success"],
                "difficulty": test_case["difficulty"],
            })

            by_difficulty[test_case["difficulty"]].append(quality)

            # Progress indicator
            if i % 5 == 0:
                print(f"    Progress: {i}/{len(test_sample)} tests complete")

        # Calculate metrics
        avg_quality = sum(r["quality"] for r in results) / len(results)
        avg_duration = sum(r["duration"] for r in results if r["success"]) / max(1, sum(1 for r in results if r["success"]))
        success_rate = sum(1 for r in results if r["success"]) / len(results)

        # Complexity profile
        complexity_profile = {
            diff: sum(scores) / len(scores) if scores else 0.0
            for diff, scores in by_difficulty.items()
        }

        # Determine break point
        break_point = None
        difficulty_order = ["SIMPLE", "MEDIUM", "COMPLEX", "V.COMPLEX", "EXTREME"]
        for diff in difficulty_order:
            if diff in complexity_profile and complexity_profile[diff] < 0.7:
                break_point = diff
                break

        metrics = {
            "model": model,
            "avg_quality": avg_quality,
            "avg_duration": avg_duration,
            "success_rate": success_rate,
            "complexity_profile": complexity_profile,
            "break_point": break_point,
            "num_samples": len(results),
        }

        # Display results
        print(f"\n  {Colors.GREEN}✓ Baseline Complete{Colors.RESET}")
        print(f"\n  {Colors.BOLD}Metrics:{Colors.RESET}")
        print(f"    Quality:      {self._color_metric(avg_quality, 0.85)}")
        print(f"    Duration:     {avg_duration:.2f}s")
        print(f"    Success Rate: {success_rate:.1%}")

        print(f"\n  {Colors.BOLD}Complexity Profile:{Colors.RESET}")
        for diff in difficulty_order:
            if diff in complexity_profile:
                score = complexity_profile[diff]
                icon = "✓" if score >= 0.7 else "✗"
                color = Colors.GREEN if score >= 0.7 else Colors.RED
                print(f"    {icon} {diff:<12s}: {color}{score:.3f}{Colors.RESET}")

        if break_point:
            print(f"\n  {Colors.RED}⚠ Break Point Detected: {break_point}{Colors.RESET}")
        else:
            print(f"\n  {Colors.GREEN}✓ No Break Point - Handles All Complexity{Colors.RESET}")

        return metrics

    def analyze_problems(self, baseline_metrics: Dict) -> List[Dict]:
        """ANALYZE: Detect performance problems."""
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}PHASE 2: ANALYZE - Detecting Problems{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        problems = []

        # Check quality threshold
        if baseline_metrics["avg_quality"] < self.thresholds["quality"]:
            severity = "HIGH" if baseline_metrics["avg_quality"] < 0.70 else "MEDIUM"
            problems.append({
                "type": "quality_low",
                "severity": severity,
                "current": baseline_metrics["avg_quality"],
                "target": self.thresholds["quality"],
                "description": f"Quality {baseline_metrics['avg_quality']:.3f} below target {self.thresholds['quality']:.3f}",
            })

        # Check success rate
        if baseline_metrics["success_rate"] < self.thresholds["success_rate"]:
            problems.append({
                "type": "reliability_low",
                "severity": "MEDIUM",
                "current": baseline_metrics["success_rate"],
                "target": self.thresholds["success_rate"],
                "description": f"Success rate {baseline_metrics['success_rate']:.1%} below target {self.thresholds['success_rate']:.1%}",
            })

        # Check complexity handling
        if baseline_metrics["break_point"]:
            problems.append({
                "type": "complexity_handling",
                "severity": "HIGH",
                "break_point": baseline_metrics["break_point"],
                "description": f"Model breaks down at {baseline_metrics['break_point']} complexity level",
            })

        if problems:
            print(f"  {Colors.RED}⚠ Detected {len(problems)} Problem(s):{Colors.RESET}\n")
            for p in problems:
                severity_color = Colors.RED if p["severity"] == "HIGH" else Colors.YELLOW
                print(f"    [{severity_color}{p['severity']}{Colors.RESET}] {p['type']}")
                print(f"        {p['description']}")
        else:
            print(f"  {Colors.GREEN}✓ No Problems Detected{Colors.RESET}")
            print(f"  {Colors.GREEN}✓ System Meets All Thresholds{Colors.RESET}")

        return problems

    async def propose_alternatives(self, baseline_metrics: Dict, problems: List[Dict]) -> List[str]:
        """STRATEGY: Propose alternative models based on problems."""
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}PHASE 3: STRATEGY - Proposing Alternatives{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        if not problems:
            print(f"  {Colors.GREEN}✓ No alternatives needed - system optimized{Colors.RESET}")
            return []

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
                if model_name and model_name != baseline_metrics["model"]:
                    available_models.append(model_name)

        # Strategy based on problems
        candidates = []

        for problem in problems:
            if problem["type"] == "quality_low":
                # Prioritize models known for quality
                quality_models = [
                    m for m in available_models
                    if any(name in m for name in ["mistral", "llama3.2:3b", "qwen2.5:32b", "gpt-oss"])
                ]
                candidates.extend(quality_models[:2])

            elif problem["type"] == "complexity_handling":
                # Models that handle complexity well
                robust_models = [
                    m for m in available_models
                    if any(name in m for name in ["mistral:7b", "llama3.2:3b", "qwen2.5:32b", "gpt-oss"])
                ]
                candidates.extend(robust_models[:2])

        # Remove duplicates and limit
        candidates = list(dict.fromkeys(candidates))[:2]

        print(f"  {Colors.BOLD}Analysis:{Colors.RESET}")
        for problem in problems:
            print(f"    • Problem: {problem['type']}")
            print(f"      Strategy: {'Focus on quality & complexity handling' if problem['type'] in ['quality_low', 'complexity_handling'] else 'Improve reliability'}")

        print(f"\n  {Colors.BOLD}Proposed Candidates:{Colors.RESET}")
        for i, candidate in enumerate(candidates, 1):
            print(f"    {i}. {candidate}")

        if not candidates:
            print(f"    {Colors.YELLOW}⚠ No suitable candidates found{Colors.RESET}")

        return candidates

    async def run_experiment(self, control_model: str, variant_models: List[str], num_samples: int = 20) -> Dict:
        """EXPERIMENT: Run A/B test with statistical analysis."""
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}PHASE 4: EXPERIMENT - A/B Testing{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        all_models = [control_model] + variant_models

        print(f"  {Colors.BOLD}Experiment Design:{Colors.RESET}")
        print(f"    Control:  {control_model}")
        for i, variant in enumerate(variant_models, 1):
            print(f"    Variant{i}: {variant}")
        print(f"    Samples:  {num_samples} per model")
        print(f"    Total:    {len(all_models) * num_samples} tests")

        # Run all models in parallel
        print(f"\n  {Colors.BOLD}Running experiment...{Colors.RESET}")

        tasks = []
        for model in all_models:
            tasks.append(self._test_model(model, num_samples))

        results = await asyncio.gather(*tasks)

        # Build experiment results
        experiment_results = {}
        for i, model in enumerate(all_models):
            experiment_results[model] = {
                "role": "control" if model == control_model else "variant",
                "metrics": results[i],
            }

        # Display results
        print(f"\n  {Colors.GREEN}✓ Experiment Complete{Colors.RESET}")
        print(f"\n  {Colors.BOLD}Results:{Colors.RESET}")
        print(f"    {'Model':<30s} {'Role':<10s} {'Quality':>10s} {'Duration':>12s} {'Success':>10s}")
        print(f"    {'-' * 75}")

        for model, data in experiment_results.items():
            role = f"({data['role']})" if data['role'] == 'control' else ""
            m = data["metrics"]
            quality_str = self._color_metric(m["avg_quality"], 0.85)
            print(f"    {model:<30s} {role:<10s} {quality_str} {m['avg_duration']:>10.2f}s  {m['success_rate']:>9.1%}")

        return experiment_results

    async def _test_model(self, model: str, num_samples: int) -> Dict:
        """Test a single model."""
        results = []

        import random
        test_sample = random.sample(TEST_CASES, min(num_samples, len(TEST_CASES)))

        for test_case in test_sample:
            prompt = EXTRACTION_PROMPT.format(text=test_case["text"])
            response, metadata = await self.client.generate(model, prompt)

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

        return {
            "avg_quality": avg_quality,
            "avg_duration": avg_duration,
            "success_rate": success_rate,
        }

    def select_winner(self, experiment_results: Dict) -> Tuple[str, float]:
        """DEPLOY: Select winner based on composite score."""
        print(f"\n{Colors.BOLD}{'═' * 100}{Colors.RESET}")
        print(f"{Colors.CYAN}{Colors.BOLD}PHASE 5: DEPLOY - Selecting Winner{Colors.RESET}")
        print(f"{Colors.BOLD}{'═' * 100}{Colors.RESET}\n")

        # Composite score: 70% quality, 20% success_rate, 10% speed
        scores = {}
        for model, data in experiment_results.items():
            m = data["metrics"]

            quality_score = m["avg_quality"]
            success_score = m["success_rate"]
            speed_score = 1.0 / m["avg_duration"] * 10 if m["avg_duration"] > 0 else 0

            composite = (
                quality_score * 0.70 +
                success_score * 0.20 +
                min(1.0, speed_score) * 0.10
            )

            scores[model] = {
                "composite": composite,
                "quality": quality_score,
                "success_rate": success_score,
            }

        # Find winner
        winner = max(scores.items(), key=lambda x: x[1]["composite"])
        winner_model = winner[0]
        winner_score = winner[1]

        # Find control
        control = [m for m, d in experiment_results.items() if d["role"] == "control"][0]

        improvement = (winner_score["quality"] - scores[control]["quality"]) / scores[control]["quality"] * 100

        print(f"  {Colors.BOLD}Composite Scoring:{Colors.RESET}")
        print("    Formula: 70% quality + 20% success_rate + 10% speed\n")

        for model, score_data in sorted(scores.items(), key=lambda x: x[1]["composite"], reverse=True):
            is_winner = model == winner_model
            prefix = f"{Colors.GREEN}🏆 " if is_winner else "   "
            suffix = Colors.RESET if is_winner else ""
            print(f"{prefix}{model:<30s}: {score_data['composite']:.3f} "
                  f"(Q:{score_data['quality']:.3f} SR:{score_data['success_rate']:.3f}){suffix}")

        if winner_model == control:
            print(f"\n  {Colors.YELLOW}⚠ Current model remains best{Colors.RESET}")
            print(f"  {Colors.YELLOW}⚠ No deployment needed{Colors.RESET}")
        else:
            print(f"\n  {Colors.GREEN}✓ Winner: {winner_model}{Colors.RESET}")
            print(f"  {Colors.GREEN}✓ Quality Improvement: {improvement:+.1f}%{Colors.RESET}")
            print(f"  {Colors.GREEN}✓ Deploying as new baseline{Colors.RESET}")

        return winner_model, improvement

    def _color_metric(self, value: float, threshold: float) -> str:
        """Color-code a metric value."""
        if value >= threshold:
            return f"{Colors.GREEN}{value:>10.3f}{Colors.RESET}"
        elif value >= threshold * 0.9:
            return f"{Colors.YELLOW}{value:>10.3f}{Colors.RESET}"
        else:
            return f"{Colors.RED}{value:>10.3f}{Colors.RESET}"


async def main():
    print("\n" + "=" * 100)
    print(f"{Colors.BOLD}M5 REAL SELF-IMPROVEMENT CYCLE - Ollama + Complexity Testing{Colors.RESET}")
    print("=" * 100)

    print(f"\n{Colors.BOLD}Configuration:{Colors.RESET}")
    print("  • Real Ollama API calls")
    print("  • Complexity-aware strategy")
    print("  • Statistical A/B testing")
    print("  • Iterative improvement cycles")
    print("  • Foundation for multi-agent workflows")

    print(f"\n{Colors.BOLD}Thresholds:{Colors.RESET}")
    print("  • Quality: ≥ 0.85")
    print("  • Success Rate: ≥ 80%")

    # Initialize
    client = OllamaClient()
    orchestrator = M5SelfImprovementOrchestrator(client)

    # Start with a baseline model
    current_model = "llama3.1:8b"
    max_cycles = 3

    print(f"\n{Colors.BOLD}Starting Model: {current_model}{Colors.RESET}")
    print(f"{Colors.BOLD}Max Cycles: {max_cycles}{Colors.RESET}")

    print(f"\n{Colors.YELLOW}⚠️  This will take 10-20 minutes depending on your hardware{Colors.RESET}")
    print(f"{Colors.YELLOW}⚠️  Each cycle runs 40-60 real LLM inference calls{Colors.RESET}")
    print(f"\n{Colors.BOLD}Starting...{Colors.RESET}")

    # Run improvement cycles
    for cycle in range(1, max_cycles + 1):
        print(f"\n\n{'█' * 100}")
        print(f"{Colors.MAGENTA}{Colors.BOLD}CYCLE {cycle}: {current_model}{Colors.RESET}")
        print(f"{'█' * 100}")

        cycle_start = time.time()

        # PHASE 1: DETECT
        baseline_metrics = await orchestrator.run_baseline(current_model, num_samples=20)

        # PHASE 2: ANALYZE
        problems = orchestrator.analyze_problems(baseline_metrics)

        # Check if we're done
        if not problems:
            print(f"\n{Colors.GREEN}{Colors.BOLD}✓ OPTIMIZATION COMPLETE!{Colors.RESET}")
            print(f"{Colors.GREEN}✓ All thresholds met, no further improvement needed{Colors.RESET}")
            orchestrator.cycle_history.append({
                "cycle": cycle,
                "model": current_model,
                "metrics": baseline_metrics,
                "action": "complete",
            })
            break

        # PHASE 3: STRATEGY
        candidates = await orchestrator.propose_alternatives(baseline_metrics, problems)

        if not candidates:
            print(f"\n{Colors.YELLOW}⚠ No suitable candidates found, stopping{Colors.RESET}")
            orchestrator.cycle_history.append({
                "cycle": cycle,
                "model": current_model,
                "metrics": baseline_metrics,
                "action": "no_candidates",
            })
            break

        # PHASE 4: EXPERIMENT
        experiment_results = await orchestrator.run_experiment(
            current_model, candidates, num_samples=20
        )

        # PHASE 5: DEPLOY
        winner, improvement = orchestrator.select_winner(experiment_results)

        cycle_duration = time.time() - cycle_start

        # Record cycle
        orchestrator.cycle_history.append({
            "cycle": cycle,
            "model": current_model,
            "metrics": baseline_metrics,
            "winner": winner,
            "improvement": improvement,
            "duration": cycle_duration,
            "action": "deployed" if winner != current_model else "no_change",
        })

        # Update current model
        if winner != current_model:
            current_model = winner
        else:
            print(f"\n{Colors.YELLOW}⚠ No improvement found, stopping{Colors.RESET}")
            break

    # Summary
    print(f"\n\n{'=' * 100}")
    print(f"{Colors.BOLD}M5 SELF-IMPROVEMENT CYCLE SUMMARY{Colors.RESET}")
    print(f"{'=' * 100}\n")

    print(f"{Colors.BOLD}Improvement Timeline:{Colors.RESET}\n")

    for i, cycle_data in enumerate(orchestrator.cycle_history):
        action = cycle_data.get("action", "unknown")

        if i == 0:
            arrow = "START"
        else:
            prev_model = orchestrator.cycle_history[i-1]["model"]
            if cycle_data["model"] != prev_model:
                arrow = f"{Colors.GREEN}↓ DEPLOYED{Colors.RESET}"
            else:
                arrow = f"{Colors.YELLOW}↓ NO CHANGE{Colors.RESET}"

        print(f"  {arrow}")
        print("  │")
        print(f"  ├─ {Colors.BOLD}Cycle {cycle_data['cycle']}: {cycle_data['model']}{Colors.RESET}")

        if "metrics" in cycle_data:
            m = cycle_data["metrics"]
            print(f"  │  Quality: {m['avg_quality']:.3f} | Success: {m['success_rate']:.1%} | Duration: {m['avg_duration']:.2f}s")

        if cycle_data.get("winner") and cycle_data["winner"] != cycle_data["model"]:
            print(f"  │  Winner: {cycle_data['winner']} (improvement: {cycle_data['improvement']:+.1f}%)")

        print("  │")

    if orchestrator.cycle_history:
        final = orchestrator.cycle_history[-1]
        initial = orchestrator.cycle_history[0]

        print(f"\n{Colors.BOLD}Overall Result:{Colors.RESET}")
        print(f"  Initial: {initial['model']}")
        print(f"  Final:   {final['model']}")

        if "metrics" in initial and "metrics" in final:
            quality_gain = (final['metrics']['avg_quality'] - initial['metrics']['avg_quality']) / initial['metrics']['avg_quality'] * 100
            print(f"  Quality: {Colors.GREEN}{quality_gain:+.1f}%{Colors.RESET} improvement")

        print(f"  Cycles:  {len(orchestrator.cycle_history)}")

    await client.close()

    print("\n" + "=" * 100)
    print(f"{Colors.GREEN}{Colors.BOLD}✓ M5 SELF-IMPROVEMENT CYCLE COMPLETE{Colors.RESET}")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

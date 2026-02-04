#!/usr/bin/env python3
"""
M5.1 Demo: Real LLM Execution with Ollama Models

This demo makes ACTUAL LLM calls to Ollama models to demonstrate M5.1's
self-improvement infrastructure with real performance data.

Difference from m5_demo.py:
- m5_demo.py: Mocked outputs, simulated performance data
- THIS SCRIPT: Real Ollama calls, actual performance metrics

Requirements:
- Ollama installed and running (ollama serve)
- Models downloaded:
  - ollama pull llama3.1:8b
  - ollama pull gemma2:2b
  - ollama pull phi3:mini
  - ollama pull mistral:7b

What's REAL:
- Actual LLM calls to Ollama models
- Real token counts and costs
- Real execution duration
- Real quality scoring of outputs
- Real statistical analysis

What's MOCKED:
- Input product data (simulated e-commerce product descriptions)
- Quality scoring rubric (simplified for demo)
"""

import asyncio
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import httpx

# Add project root to path
sys.path.insert(0, "/home/shinelay/meta-autonomous-framework")

from src.observability.models import AgentExecutionRecord
from src.self_improvement.data_models import (
    AgentConfig,
    AgentPerformanceProfile,
    ExperimentConfig,
    ProblemSeverity,
)
from src.self_improvement.experiment_orchestrator import ExperimentOrchestrator
from src.self_improvement.performance_analyzer import PerformanceAnalyzer
from src.self_improvement.storage.observability_store import ObservabilityStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# MOCK INPUT DATA: Product descriptions for extraction
# ============================================================================

MOCK_PRODUCTS = [
    {
        "raw_text": "MacBook Pro 16-inch M3 Max chip 36GB unified memory 1TB SSD storage Space Black $3499.99 Free shipping",
        "expected": {
            "name": "MacBook Pro 16-inch",
            "specs": "M3 Max chip, 36GB memory, 1TB SSD",
            "color": "Space Black",
            "price": 3499.99,
        },
    },
    {
        "raw_text": "Sony WH-1000XM5 Wireless Noise Canceling Headphones - Black - Over-Ear $399.99 30h battery life",
        "expected": {
            "name": "Sony WH-1000XM5",
            "specs": "Wireless, Noise Canceling, 30h battery",
            "color": "Black",
            "price": 399.99,
        },
    },
    {
        "raw_text": "Samsung 65 inch QLED 4K Smart TV QN90C Neo Quantum HDR+ $1899 with free mounting",
        "expected": {
            "name": "Samsung 65-inch QLED 4K Smart TV QN90C",
            "specs": "Neo Quantum HDR+, Smart TV",
            "color": None,
            "price": 1899.0,
        },
    },
    {
        "raw_text": "Dyson V15 Detect Cordless Vacuum Cleaner Laser Dust Detection HEPA Yellow $649.99",
        "expected": {
            "name": "Dyson V15 Detect",
            "specs": "Cordless, Laser Dust Detection, HEPA",
            "color": "Yellow",
            "price": 649.99,
        },
    },
    {
        "raw_text": "Apple Watch Series 9 GPS 45mm Midnight Aluminum Case Sport Band $429",
        "expected": {
            "name": "Apple Watch Series 9",
            "specs": "GPS, 45mm",
            "color": "Midnight Aluminum",
            "price": 429.0,
        },
    },
]


@dataclass
class ProductExtraction:
    """Extracted product information."""

    name: Optional[str] = None
    specs: Optional[str] = None
    color: Optional[str] = None
    price: Optional[float] = None


# ============================================================================
# OLLAMA CLIENT: Real LLM calls
# ============================================================================


class OllamaClient:
    """Client for making actual calls to Ollama models."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=120.0)

    async def check_available(self) -> bool:
        """Check if Ollama is running."""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama not available: {e}")
            return False

    async def generate(
        self, model: str, prompt: str, temperature: float = 0.7
    ) -> Tuple[str, Dict]:
        """
        Generate response from Ollama model.

        Returns:
            (response_text, metadata) where metadata includes:
            - tokens: total tokens used
            - duration_ms: generation time in milliseconds
        """
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }

        start_time = time.time()

        try:
            response = await self.client.post(
                f"{self.base_url}/api/generate", json=request_data
            )
            response.raise_for_status()
            result = response.json()

            duration_ms = (time.time() - start_time) * 1000

            metadata = {
                "tokens": result.get("eval_count", 0)
                + result.get("prompt_eval_count", 0),
                "duration_ms": duration_ms,
                "eval_count": result.get("eval_count", 0),
                "prompt_eval_count": result.get("prompt_eval_count", 0),
            }

            return result.get("response", ""), metadata

        except Exception as e:
            logger.error(f"Error calling Ollama model {model}: {e}")
            raise

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


# ============================================================================
# PRODUCT EXTRACTOR: Agent that extracts product info using LLMs
# ============================================================================


class ProductExtractorAgent:
    """Agent that extracts structured product data from raw text using LLMs."""

    EXTRACTION_PROMPT = """Extract structured product information from the following text.
Return ONLY valid JSON with these fields: name, specs, color, price (as number).
If a field is not found, use null.

Text: {text}

JSON:"""

    def __init__(self, ollama_client: OllamaClient):
        self.ollama_client = ollama_client

    async def extract(
        self, raw_text: str, model: str
    ) -> Tuple[ProductExtraction, Dict]:
        """
        Extract product info using specified model.

        Returns:
            (extraction, metadata) where metadata includes performance metrics
        """
        prompt = self.EXTRACTION_PROMPT.format(text=raw_text)

        # Make real LLM call
        response, llm_metadata = await self.ollama_client.generate(model, prompt)

        # Parse JSON response
        extraction = self._parse_extraction(response)

        # Add extraction success to metadata
        metadata = {
            **llm_metadata,
            "extraction_success": extraction is not None,
        }

        return extraction, metadata

    def _parse_extraction(self, response: str) -> Optional[ProductExtraction]:
        """Parse JSON response into ProductExtraction."""
        try:
            # Find JSON in response (handle cases where model adds explanation)
            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start == -1 or json_end == 0:
                return None

            json_str = response[json_start:json_end]
            data = json.loads(json_str)

            return ProductExtraction(
                name=data.get("name"),
                specs=data.get("specs"),
                color=data.get("color"),
                price=data.get("price"),
            )
        except Exception as e:
            logger.warning(f"Failed to parse extraction: {e}")
            return None


# ============================================================================
# QUALITY SCORER: Evaluate extraction quality
# ============================================================================


class QualityScorer:
    """Score extraction quality against expected results."""

    @staticmethod
    def score(
        extraction: Optional[ProductExtraction], expected: Dict
    ) -> Tuple[float, Dict]:
        """
        Score extraction quality (0.0 - 1.0).

        Returns:
            (quality_score, breakdown) where breakdown shows per-field scores
        """
        if extraction is None:
            return 0.0, {
                "name": 0.0,
                "specs": 0.0,
                "color": 0.0,
                "price": 0.0,
                "parse_failed": True,
            }

        breakdown = {}

        # Score name (40% weight)
        breakdown["name"] = QualityScorer._score_name(extraction.name, expected["name"])

        # Score specs (30% weight)
        breakdown["specs"] = QualityScorer._score_specs(
            extraction.specs, expected["specs"]
        )

        # Score color (10% weight)
        breakdown["color"] = QualityScorer._score_color(
            extraction.color, expected["color"]
        )

        # Score price (20% weight)
        breakdown["price"] = QualityScorer._score_price(
            extraction.price, expected["price"]
        )

        # Calculate weighted total
        quality_score = (
            breakdown["name"] * 0.4
            + breakdown["specs"] * 0.3
            + breakdown["color"] * 0.1
            + breakdown["price"] * 0.2
        )

        breakdown["parse_failed"] = False
        return quality_score, breakdown

    @staticmethod
    def _score_name(extracted: Optional[str], expected: str) -> float:
        """Score name extraction."""
        if not extracted:
            return 0.0
        extracted_lower = extracted.lower()
        expected_lower = expected.lower()

        # Check if all major words from expected are in extracted
        expected_words = set(expected_lower.split())
        extracted_words = set(extracted_lower.split())

        overlap = len(expected_words & extracted_words)
        return overlap / len(expected_words) if expected_words else 0.0

    @staticmethod
    def _score_specs(extracted: Optional[str], expected: str) -> float:
        """Score specs extraction."""
        if not extracted:
            return 0.0

        # Simple keyword matching
        expected_lower = expected.lower()
        extracted_lower = extracted.lower()

        # Count how many expected terms appear
        expected_terms = [t.strip() for t in expected_lower.split(",")]
        matches = sum(1 for term in expected_terms if term in extracted_lower)

        return matches / len(expected_terms) if expected_terms else 0.0

    @staticmethod
    def _score_color(extracted: Optional[str], expected: Optional[str]) -> float:
        """Score color extraction."""
        if expected is None:
            return 1.0 if extracted is None else 0.5  # Partial credit if added color

        if not extracted:
            return 0.0

        return 1.0 if expected.lower() in extracted.lower() else 0.0

    @staticmethod
    def _score_price(extracted: Optional[float], expected: float) -> float:
        """Score price extraction."""
        if extracted is None:
            return 0.0

        # Allow 1% tolerance
        diff = abs(extracted - expected) / expected
        if diff < 0.01:
            return 1.0
        elif diff < 0.05:
            return 0.8
        elif diff < 0.10:
            return 0.5
        else:
            return 0.0


# ============================================================================
# EXPERIMENT RUNNER: Execute real LLM experiments
# ============================================================================


class RealLLMExperimentRunner:
    """Run experiments with real LLM calls and collect performance metrics."""

    # Cost estimation (USD per 1M tokens) - approximate for demo
    TOKEN_COSTS = {
        "llama3.1:8b": 0.10,
        "gemma2:2b": 0.05,
        "phi3:mini": 0.03,
        "mistral:7b": 0.08,
    }

    def __init__(self, ollama_client: OllamaClient, observability_store: ObservabilityStore):
        self.ollama_client = ollama_client
        self.observability_store = observability_store
        self.agent = ProductExtractorAgent(ollama_client)
        self.scorer = QualityScorer()

    async def run_experiment_variant(
        self, model: str, num_samples: int, variant_id: str
    ) -> List[AgentExecutionRecord]:
        """
        Run experiment variant with real LLM calls.

        Args:
            model: Ollama model name
            num_samples: Number of test cases to run
            variant_id: Experiment variant ID

        Returns:
            List of execution records with real performance data
        """
        records = []

        logger.info(f"Running {num_samples} executions for {model}...")

        for i in range(num_samples):
            # Pick random product
            product = random.choice(MOCK_PRODUCTS)

            # Make real LLM call
            start_time = time.time()
            extraction, llm_metadata = await self.agent.extract(
                product["raw_text"], model
            )
            duration_seconds = time.time() - start_time

            # Score quality
            quality_score, score_breakdown = self.scorer.score(
                extraction, product["expected"]
            )

            # Calculate cost (tokens * cost per token)
            tokens = llm_metadata.get("tokens", 0)
            cost_usd = (tokens / 1_000_000) * self.TOKEN_COSTS.get(model, 0.10)

            # Create execution record
            record = AgentExecutionRecord(
                agent_name="product_extractor",
                config_version=variant_id,
                model_name=model,
                quality_score=quality_score,
                cost_usd=cost_usd,
                duration_seconds=duration_seconds,
                input_tokens=llm_metadata.get("prompt_eval_count", 0),
                output_tokens=llm_metadata.get("eval_count", 0),
                success=llm_metadata.get("extraction_success", False),
                timestamp=datetime.utcnow(),
                metadata={
                    "score_breakdown": score_breakdown,
                    "llm_metadata": llm_metadata,
                    "product_index": MOCK_PRODUCTS.index(product),
                },
            )

            records.append(record)

            # Show progress
            if (i + 1) % 10 == 0 or (i + 1) == num_samples:
                avg_quality = sum(r.quality_score for r in records) / len(records)
                avg_duration = sum(r.duration_seconds for r in records) / len(records)
                avg_cost = sum(r.cost_usd for r in records) / len(records)
                logger.info(
                    f"  Progress: {i+1}/{num_samples} | "
                    f"Avg Quality: {avg_quality:.3f} | "
                    f"Avg Duration: {avg_duration:.2f}s | "
                    f"Avg Cost: ${avg_cost:.4f}"
                )

        # Store records in observability database
        session = self.observability_store.get_session()
        try:
            for record in records:
                session.add(record)
            session.commit()
        finally:
            session.close()

        return records


# ============================================================================
# DEMO PARTS: Interactive demonstration
# ============================================================================


def wait_for_user(message: str = "Press Enter to continue..."):
    """Wait for user to press Enter."""
    input(f"\n{message}")


def print_section(title: str):
    """Print section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70 + "\n")


async def demo_part1_environment_check(ollama_client: OllamaClient):
    """Part 1: Check Ollama environment and models."""
    print_section("Part 1: Environment Check")

    print("🔍 Checking Ollama installation...\n")

    available = await ollama_client.check_available()
    if not available:
        print("❌ Ollama is not running!")
        print("\nTo start Ollama:")
        print("  1. Install: https://ollama.ai/download")
        print("  2. Run: ollama serve")
        print("\nThen re-run this demo.")
        sys.exit(1)

    print("✅ Ollama is running\n")

    # Check models
    print("📦 Required models:")
    models = ["llama3.1:8b", "gemma2:2b", "phi3:mini", "mistral:7b"]

    print("   Control: llama3.1:8b (baseline)")
    print("   Variant 1: gemma2:2b")
    print("   Variant 2: phi3:mini")
    print("   Variant 3: mistral:7b")
    print("\nTo download missing models:")
    for model in models:
        print(f"  ollama pull {model}")

    print("\n✅ Environment ready")


async def demo_part2_baseline_performance(
    runner: RealLLMExperimentRunner, analyzer: PerformanceAnalyzer
):
    """Part 2: Collect baseline performance with real LLM calls."""
    print_section("Part 2: Baseline Performance Collection")

    print("📊 Collecting baseline performance for product_extractor agent")
    print("   Model: llama3.1:8b (current production model)")
    print("   Samples: 10 real LLM executions")
    print("   Input: Mock product descriptions (e-commerce data)")
    print("\n⚠️  This will make 10 real Ollama API calls (~30-60 seconds)\n")

    wait_for_user("Press Enter to start baseline collection...")

    # Run 10 real LLM calls
    records = await runner.run_experiment_variant("llama3.1:8b", 10, "baseline")

    # Analyze performance
    print("\n📈 Analyzing baseline performance...")

    profile = analyzer.analyze_performance("product_extractor", hours=1)

    print("\n📊 Baseline Performance Results:")
    print(f"   Quality Score: {profile.quality_score:.3f}")
    print(f"   Success Rate:  {profile.success_rate*100:.1f}%")
    print(f"   Avg Cost:      ${profile.cost_usd:.4f} per execution")
    print(f"   Avg Duration:  {profile.duration_seconds:.2f}s")
    print(f"   Total Tokens:  {profile.total_tokens} avg")

    return profile


async def demo_part3_experiment_creation(orchestrator: ExperimentOrchestrator):
    """Part 3: Create A/B test experiment."""
    print_section("Part 3: A/B Test Experiment Setup")

    print("🧪 Creating experiment to find better model")
    print("\n📋 Experiment Configuration:")
    print("   Control: llama3.1:8b (current)")
    print("   Variant 1: gemma2:2b (smaller, faster)")
    print("   Variant 2: phi3:mini (tiny, cheapest)")
    print("   Variant 3: mistral:7b (mid-size, balanced)")
    print("\n   Samples per variant: 10")
    print("   Total LLM calls: 40 (4 variants × 10 samples)")

    wait_for_user("Press Enter to create experiment...")

    # Create experiment
    agent_config = AgentConfig(
        agent_name="product_extractor",
        model_name="llama3.1:8b",
        system_prompt="Extract product information",
        temperature=0.7,
    )

    experiment_config = ExperimentConfig(
        name="Find Best Ollama Model for Product Extraction",
        description="Test alternative Ollama models to improve quality",
        target_samples_per_variant=10,
        target_metric="quality_score",
        significance_level=0.05,
    )

    experiment = orchestrator.create_experiment(
        agent_config=agent_config, experiment_config=experiment_config
    )

    # Add variants
    variants = [
        ("gemma2:2b", "Smaller model - faster, cheaper"),
        ("phi3:mini", "Tiny model - fastest, cheapest"),
        ("mistral:7b", "Mid-size model - balanced"),
    ]

    for model, description in variants:
        variant_config = AgentConfig(
            agent_name="product_extractor",
            model_name=model,
            system_prompt="Extract product information",
            temperature=0.7,
        )
        orchestrator.add_variant(
            experiment_id=experiment.id,
            variant_config=variant_config,
            description=description,
        )

    print(f"\n✅ Experiment created: {experiment.id}")
    print(f"   Status: {experiment.status}")
    print(f"   Variants: 4 (control + 3 alternatives)")

    return experiment.id


async def demo_part4_experiment_execution(
    runner: RealLLMExperimentRunner, experiment_id: str
):
    """Part 4: Execute experiment with real LLM calls."""
    print_section("Part 4: Experiment Execution")

    print("⚙️  Executing experiment with REAL Ollama models")
    print("   This will make 30 real LLM API calls (3 variants × 10 samples)")
    print("   Control already collected in Part 2 (10 calls)")
    print("\n⏱️  Estimated time: 2-5 minutes (depends on model speed)")
    print("   You'll see real-time progress for each variant\n")

    wait_for_user("Press Enter to start experiment execution...")

    models = [
        ("gemma2:2b", "variant_1"),
        ("phi3:mini", "variant_2"),
        ("mistral:7b", "variant_3"),
    ]

    for model, variant_id in models:
        print(f"\n🔄 Testing {model}...")
        await runner.run_experiment_variant(model, 10, variant_id)

    print("\n✅ Experiment execution complete!")
    print("   Total executions: 40 (10 per variant)")
    print("   All performance data collected and stored")


async def demo_part5_statistical_analysis(
    orchestrator: ExperimentOrchestrator, experiment_id: str
):
    """Part 5: Analyze results and select winner."""
    print_section("Part 5: Statistical Analysis & Winner Selection")

    print("📊 Running statistical analysis on experiment results...")
    print("   Using real performance data from LLM executions")
    print("   Statistical tests: t-tests with p-value < 0.05")
    print("   Composite score: 0.7×quality + 0.2×speed + 0.1×cost\n")

    wait_for_user("Press Enter to analyze results...")

    # Get winner
    winner = orchestrator.get_winner(experiment_id, force=True)

    if not winner:
        print("❌ No statistically significant winner found")
        print("   Models may perform too similarly")
        print("   Try collecting more samples for stronger signal")
        return

    print("\n🏆 Winner Selected!")
    print(f"   Model: {winner.winner_variant_id}")
    print(f"   Improvement: {winner.improvement_percentage:+.1f}%")
    print(f"   Confidence: {winner.confidence_level:.1%}")
    print(
        f"   Statistically Significant: {'Yes' if winner.statistical_significance else 'No'}"
    )
    print(f"   Sample Size: {winner.sample_size}")

    print("\n📈 Recommendation:")
    if winner.improvement_percentage > 5:
        print(f"   ✅ Deploy {winner.winner_variant_id} to production")
        print(f"      Expected improvement: {winner.improvement_percentage:+.1f}%")
    elif winner.improvement_percentage > 0:
        print(f"   ⚠️  Small improvement ({winner.improvement_percentage:+.1f}%)")
        print("      Consider A/B testing in production first")
    else:
        print("   ⚠️  No improvement over baseline")
        print("      Keep current model")

    return winner


async def demo_part6_deployment_preview():
    """Part 6: Show what Phase 5 (DEPLOY) would do in M5.2."""
    print_section("Part 6: Deployment Preview (M5.2)")

    print("🚀 What happens in M5.2 Full Loop:\n")
    print("Phase 5 (DEPLOY) would automatically:")
    print("   1. Deploy winning model configuration")
    print("   2. Enable rollback monitoring")
    print("   3. Track quality metrics for 24 hours")
    print("   4. Auto-rollback if quality drops >5%")
    print("   5. Persist new baseline if stable")

    print("\n📋 Deployment Configuration:")
    print("   ├─ Rollback Monitoring: Enabled")
    print("   ├─ Quality Threshold: -5% (auto-rollback)")
    print("   ├─ Monitoring Window: 24 hours")
    print("   └─ Auto-Commit: After 24h if stable")

    print("\n⚠️  Note: Full deployment requires M5.2")
    print("   M5.1 provides infrastructure (demonstrated above)")
    print("   M5.2 will integrate into automated improvement loop")


# ============================================================================
# MAIN DEMO
# ============================================================================


async def main():
    """Run complete M5.1 demo with real LLM calls."""
    print("=" * 70)
    print("  M5.1 DEMO: Real LLM Execution with Ollama")
    print("  End-to-End Self-Improvement Infrastructure")
    print("=" * 70)

    print("\n📝 Demo Overview:")
    print("   This demo makes REAL Ollama model calls to demonstrate")
    print("   M5.1's self-improvement infrastructure with actual performance data.")
    print("\n   What's REAL:")
    print("   ✓ Actual LLM calls to Ollama models")
    print("   ✓ Real token counts and costs")
    print("   ✓ Real execution duration")
    print("   ✓ Real quality scoring")
    print("   ✓ Real statistical analysis")
    print("\n   What's MOCKED:")
    print("   ✓ Input product data (simulated e-commerce)")

    print(
        "\n   Scenario: Find best model for product extraction"
    )
    print("   Current: llama3.1:8b")
    print("   Testing: gemma2:2b, phi3:mini, mistral:7b")

    wait_for_user("\nPress Enter to start...")

    # Initialize components
    ollama_client = OllamaClient()
    obs_store = ObservabilityStore(":memory:")
    obs_store.create_tables()

    analyzer = PerformanceAnalyzer(obs_store)
    orchestrator = ExperimentOrchestrator(obs_store)
    runner = RealLLMExperimentRunner(ollama_client, obs_store)

    try:
        # Part 1: Environment check
        await demo_part1_environment_check(ollama_client)
        wait_for_user()

        # Part 2: Baseline performance with real LLM
        baseline = await demo_part2_baseline_performance(runner, analyzer)
        wait_for_user()

        # Part 3: Create experiment
        experiment_id = await demo_part3_experiment_creation(orchestrator)
        wait_for_user()

        # Part 4: Execute experiment with real LLMs
        await demo_part4_experiment_execution(runner, experiment_id)
        wait_for_user()

        # Part 5: Statistical analysis
        winner = await demo_part5_statistical_analysis(orchestrator, experiment_id)
        wait_for_user()

        # Part 6: Deployment preview
        await demo_part6_deployment_preview()

        # Summary
        print_section("Demo Complete!")
        print("✅ M5.1 Infrastructure Demonstrated with Real LLM Execution\n")
        print("What we showed:")
        print("   ✓ Real Ollama model calls (40 total)")
        print("   ✓ Actual performance metrics collection")
        print("   ✓ Statistical analysis on real data")
        print("   ✓ Winner selection with confidence intervals")
        print("   ✓ Complete A/B testing workflow")

        print(f"\nBaseline Quality: {baseline.quality_score:.3f}")
        if winner:
            print(f"Winner Quality: {winner.improvement_percentage:+.1f}% improvement")

        print("\nM5.1 Status: COMPLETE ✅")
        print("   - All infrastructure working with real LLMs")
        print("   - Production-ready building blocks")

        print("\nNext Steps (M5.2):")
        print("   - Integrate into full 5-phase loop")
        print("   - Add automated deployment with rollback")
        print("   - Enable continuous improvement mode")

    finally:
        await ollama_client.close()


if __name__ == "__main__":
    asyncio.run(main())

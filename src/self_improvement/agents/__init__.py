"""
M5 Self-Improvement Agents.

Collection of benchmark agents used for M5 experimentation and testing.
These agents serve as workloads to evaluate different model configurations,
prompt strategies, and optimization techniques.
"""
from src.self_improvement.agents.product_extractor import ProductExtractorAgent

__all__ = [
    "ProductExtractorAgent",
]

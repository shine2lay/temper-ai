"""Detects reusable stage configurations across portfolio products."""

import logging
import uuid
from pathlib import Path
from typing import Dict, List, Set

import yaml

from src.portfolio._schemas import ComponentMatch, PortfolioConfig
from src.portfolio._tracking import track_portfolio_event
from src.portfolio.constants import MIN_SIMILARITY_THRESHOLD
from src.portfolio.models import SharedComponentRecord
from src.portfolio.store import PortfolioStore
from src.storage.database.datetime_utils import utcnow

logger = logging.getLogger(__name__)


class ComponentAnalyzer:
    """Detects reusable stage configurations across products."""

    def __init__(self, store: PortfolioStore) -> None:
        self.store = store

    def analyze_portfolio(
        self, portfolio: PortfolioConfig,
    ) -> List[ComponentMatch]:
        """Analyze all products for shared stage configurations.

        Loads workflow configs, extracts stage definitions, computes
        pairwise Jaccard similarity, and persists matches above threshold.
        """
        product_stages: Dict[str, Dict[str, Set[str]]] = {}

        for product in portfolio.products:
            stages = _load_stages_for_product(product.workflow_configs)
            if stages:
                product_stages[product.name] = stages

        matches: List[ComponentMatch] = []
        product_names = list(product_stages.keys())

        for i in range(len(product_names)):
            for j in range(i + 1, len(product_names)):
                p_a = product_names[i]
                p_b = product_names[j]
                new_matches = _compare_products(
                    p_a,
                    product_stages[p_a],
                    p_b,
                    product_stages[p_b],
                )
                matches.extend(new_matches)

        for match in matches:
            self._save_match(match)

        logger.info(
            "Portfolio analysis complete: %d shared components found",
            len(matches),
        )
        track_portfolio_event(
            "component_analysis",
            {"product_count": len(product_stages)},
            "completed",
            impact_metrics={"matches_found": len(matches)},
            tags=["portfolio", "component_analyzer"],
        )
        return matches

    def find_similar_stages(
        self,
        stage_config: Dict,
        product_type: str,
        min_similarity: float = MIN_SIMILARITY_THRESHOLD,
    ) -> List[ComponentMatch]:
        """Find stages similar to a given config within stored components."""
        query_keys = set(_flatten_keys(stage_config))
        records = self.store.list_shared_components(
            min_similarity=min_similarity,
        )

        results: List[ComponentMatch] = []
        for rec in records:
            if (
                rec.source_stage.startswith(product_type + "/")
                or rec.target_stage.startswith(product_type + "/")
            ):
                if rec.similarity >= min_similarity:
                    shared = set(rec.shared_keys) & query_keys
                    if shared:
                        results.append(
                            ComponentMatch(
                                source_stage=rec.source_stage,
                                target_stage=rec.target_stage,
                                similarity=rec.similarity,
                                shared_keys=sorted(shared),
                                differing_keys=rec.differing_keys,
                            )
                        )
        track_portfolio_event(
            "find_similar_stages",
            {"product_type": product_type, "min_similarity": min_similarity},
            "completed",
            impact_metrics={"results_found": len(results)},
            tags=["portfolio", "component_analyzer"],
        )
        return results

    @staticmethod
    def jaccard_similarity(
        keys_a: Set[str], keys_b: Set[str],
    ) -> float:
        """|A intersection B| / |A union B|, 0.0 for empty sets."""
        if not keys_a and not keys_b:
            return 0.0
        union = keys_a | keys_b
        if not union:
            return 0.0
        return len(keys_a & keys_b) / len(union)

    def _save_match(self, match: ComponentMatch) -> None:
        """Persist a ComponentMatch as a SharedComponentRecord."""
        record = SharedComponentRecord(
            id=str(uuid.uuid4()),
            source_stage=match.source_stage,
            target_stage=match.target_stage,
            similarity=match.similarity,
            shared_keys=match.shared_keys,
            differing_keys=match.differing_keys,
            created_at=utcnow(),
        )
        self.store.save_shared_component(record)


def _load_stages_for_product(
    workflow_configs: List[str],
) -> Dict[str, Set[str]]:
    """Load workflow YAML files and extract stage key sets."""
    stages: Dict[str, Set[str]] = {}
    for config_path in workflow_configs:
        path = Path(config_path)
        if not path.exists():
            logger.debug("Workflow config not found: %s", config_path)
            continue
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError:
            logger.warning("Failed to parse YAML: %s", config_path)
            continue
        if not isinstance(data, dict):
            continue
        _extract_stages(data, config_path, stages)
    return stages


def _extract_stages(
    data: Dict, config_path: str, out: Dict[str, Set[str]],
) -> None:
    """Extract stage definitions from a parsed workflow config."""
    raw_stages = data.get("stages", [])
    if isinstance(raw_stages, list):
        for stage in raw_stages:
            if isinstance(stage, dict):
                name = stage.get("name", stage.get("stage_ref", ""))
                if name:
                    key = f"{config_path}/{name}"
                    out[key] = set(_flatten_keys(stage))
    elif isinstance(raw_stages, dict):
        for name, stage_data in raw_stages.items():
            if isinstance(stage_data, dict):
                key = f"{config_path}/{name}"
                out[key] = set(_flatten_keys(stage_data))


def _flatten_keys(d: Dict, prefix: str = "") -> List[str]:
    """Flatten a nested dict into dot-delimited key paths."""
    keys: List[str] = []
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else str(k)
        keys.append(full_key)
        if isinstance(v, dict):
            keys.extend(_flatten_keys(v, full_key))
    return keys


def _compare_products(
    p_a: str,
    stages_a: Dict[str, Set[str]],
    p_b: str,
    stages_b: Dict[str, Set[str]],
) -> List[ComponentMatch]:
    """Compare stages between two products and return matches."""
    matches: List[ComponentMatch] = []
    for name_a, keys_a in stages_a.items():
        for name_b, keys_b in stages_b.items():
            sim = ComponentAnalyzer.jaccard_similarity(keys_a, keys_b)
            if sim >= MIN_SIMILARITY_THRESHOLD:
                shared = sorted(keys_a & keys_b)
                differing = sorted(
                    (keys_a | keys_b) - (keys_a & keys_b)
                )
                matches.append(
                    ComponentMatch(
                        source_stage=f"{p_a}/{name_a}",
                        target_stage=f"{p_b}/{name_b}",
                        similarity=sim,
                        shared_keys=shared,
                        differing_keys=differing,
                    )
                )
    return matches

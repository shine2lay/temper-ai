"""Knowledge graph populator and query engine for portfolio management."""

import logging
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import yaml

from src.portfolio._schemas import KGConceptType, KGRelation, PortfolioConfig
from src.portfolio.constants import DEFAULT_BFS_DEPTH, DEFAULT_RUN_LIMIT, MAX_BFS_DEPTH
from src.portfolio.models import (
    KGConceptRecord,
    KGEdgeRecord,
    TechCompatibilityRecord,
)
from src.portfolio.store import PortfolioStore

logger = logging.getLogger(__name__)


class KnowledgePopulator:
    """Populate the knowledge graph from portfolio configs and run data."""

    def __init__(self, store: PortfolioStore) -> None:
        self.store = store

    def populate_from_config(self, portfolio: PortfolioConfig) -> int:
        """Create concepts/edges from a portfolio config.

        Returns the count of NEW concepts added.
        """
        added = 0
        for product in portfolio.products:
            added += self._populate_product(product.name, product.workflow_configs)
        return added

    def _populate_product(self, product_name: str, workflow_configs: List[str]) -> int:
        """Create concepts for a single product and its workflows."""
        added = 0
        product_concept = self._ensure_concept(
            product_name, KGConceptType.PRODUCT,
        )
        if product_concept is not None:
            added += 1

        product_id = self._get_concept_id(product_name)
        for wf_path in workflow_configs:
            added += self._populate_workflow(product_id, wf_path)
        return added

    def _populate_workflow(self, product_id: str, wf_path: str) -> int:
        """Parse a workflow YAML and create stage/agent concepts."""
        added = 0
        stages = self._extract_stages(wf_path)
        for stage_name, agent_names in stages:
            stage_concept = self._ensure_concept(
                stage_name, KGConceptType.STAGE,
            )
            if stage_concept is not None:
                added += 1
            stage_id = self._get_concept_id(stage_name)
            self._ensure_edge(product_id, stage_id, KGRelation.USES)
            added += self._populate_agents(stage_id, agent_names)
        return added

    def _populate_agents(self, stage_id: str, agent_names: List[str]) -> int:
        """Create agent concepts and link them to a stage."""
        added = 0
        for agent_name in agent_names:
            agent_concept = self._ensure_concept(
                agent_name, KGConceptType.AGENT,
            )
            if agent_concept is not None:
                added += 1
            agent_id = self._get_concept_id(agent_name)
            self._ensure_edge(stage_id, agent_id, KGRelation.HAS_AGENT)
        return added

    def _extract_stages(self, wf_path: str) -> List[tuple]:
        """Load a workflow YAML and return (stage_name, agent_names) pairs."""
        path = Path(wf_path)
        if not path.exists():
            logger.warning("Workflow config not found: %s", wf_path)
            return []
        try:
            with open(path) as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError:
            logger.warning("Invalid YAML in workflow config: %s", wf_path)
            return []
        if not raw:
            return []
        return self._parse_stages_from_raw(raw)

    def _parse_stages_from_raw(self, raw: Dict[str, Any]) -> List[tuple]:
        """Extract stage names and agent names from parsed workflow data."""
        workflow = raw.get("workflow", raw)
        stages_raw = workflow.get("stages", [])
        result = []
        for stage_entry in stages_raw:
            stage_name = stage_entry.get("name", "")
            if not stage_name:
                continue
            agents = self._extract_agents_from_stage(stage_entry)
            result.append((stage_name, agents))
        return result

    def _extract_agents_from_stage(self, stage_entry: Dict[str, Any]) -> List[str]:
        """Extract agent names from a stage entry or its referenced config."""
        agents = stage_entry.get("agents", [])
        if agents:
            return [a if isinstance(a, str) else a.get("name", "") for a in agents]
        stage_ref = stage_entry.get("stage_ref", "")
        if not stage_ref:
            return []
        return self._load_agents_from_stage_ref(stage_ref)

    def _load_agents_from_stage_ref(self, stage_ref: str) -> List[str]:
        """Load agent names from a stage reference YAML file."""
        ref_path = Path(stage_ref)
        if not ref_path.exists():
            return []
        try:
            with open(ref_path) as f:
                stage_raw = yaml.safe_load(f)
        except yaml.YAMLError:
            return []
        if not stage_raw:
            return []
        stage_data = stage_raw.get("stage", stage_raw)
        agents = stage_data.get("agents", [])
        return [a if isinstance(a, str) else a.get("name", "") for a in agents]

    def populate_from_runs(self, product_type: str, limit: int = DEFAULT_RUN_LIMIT) -> int:
        """Create outcome concepts from product run history.

        Returns the count of new concepts added.
        """
        runs = self.store.list_product_runs(product_type=product_type, limit=limit)
        product_concept = self.store.get_concept(product_type)
        if product_concept is None:
            logger.warning(
                "Product concept '%s' not found; skipping run population",
                product_type,
            )
            return 0

        added = 0
        for run in runs:
            outcome_name = f"{product_type}:{run.status}:{run.id}"
            outcome = self._ensure_concept(outcome_name, KGConceptType.OUTCOME)
            if outcome is not None:
                added += 1
            outcome_id = self._get_concept_id(outcome_name)
            self._ensure_edge(
                product_concept.id, outcome_id, KGRelation.PRODUCED_RESULT,
            )
        return added

    def add_tech_compatibility(
        self, tech_a: str, tech_b: str, score: float, notes: str = "",
    ) -> None:
        """Record a technology compatibility assessment."""
        record = TechCompatibilityRecord(
            id=str(uuid4()),
            tech_a=tech_a,
            tech_b=tech_b,
            compatibility_score=score,
            notes=notes,
        )
        self.store.save_compatibility(record)

    # ── Helpers ────────────────────────────────────────────────────────

    def _ensure_concept(
        self, name: str, concept_type: KGConceptType,
    ) -> Optional[KGConceptRecord]:
        """Create a concept if it does not exist. Returns the record if new."""
        existing = self.store.get_concept(name)
        if existing is not None:
            return None
        record = KGConceptRecord(
            id=str(uuid4()),
            name=name,
            concept_type=concept_type.value,
        )
        self.store.save_concept(record)
        return record

    def _get_concept_id(self, name: str) -> str:
        """Get the ID of a concept by name. Assumes it exists."""
        concept = self.store.get_concept(name)
        if concept is None:
            raise ValueError(f"Concept not found: {name}")
        return concept.id

    def _ensure_edge(
        self, source_id: str, target_id: str, relation: KGRelation,
    ) -> None:
        """Create an edge if it does not already exist."""
        existing = self.store.query_edges(
            source_id=source_id, target_id=target_id, relation=relation.value,
        )
        if existing:
            return
        record = KGEdgeRecord(
            id=str(uuid4()),
            source_id=source_id,
            target_id=target_id,
            relation=relation.value,
        )
        self.store.save_edge(record)


class KnowledgeQuery:
    """Query engine for the portfolio knowledge graph."""

    def __init__(self, store: PortfolioStore) -> None:
        self.store = store

    def get_related_concepts(
        self,
        concept_name: str,
        relation: Optional[str] = None,
        depth: int = DEFAULT_BFS_DEPTH,
    ) -> List[Dict[str, Any]]:
        """BFS traversal to find related concepts.

        Returns list of dicts with name, concept_type, relation, depth.
        """
        start = self.store.get_concept(concept_name)
        if start is None:
            return []

        results: List[Dict[str, Any]] = []
        visited: set[str] = {start.id}
        queue: deque[tuple[str, int]] = deque([(start.id, 0)])

        while queue:
            current_id, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            neighbors = self._get_neighbors(current_id, relation)
            for neighbor_id, edge_relation in neighbors:
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                concept = self.store.get_concept_by_id(neighbor_id)
                if concept is None:
                    continue
                results.append({
                    "name": concept.name,
                    "concept_type": concept.concept_type,
                    "relation": edge_relation,
                    "depth": current_depth + 1,
                })
                queue.append((neighbor_id, current_depth + 1))
        return results

    def find_path(
        self, source: str, target: str, max_depth: int = MAX_BFS_DEPTH,
    ) -> Optional[List[str]]:
        """BFS shortest path between two concepts.

        Returns list of concept names along the path, or None if no path.
        """
        start = self.store.get_concept(source)
        end = self.store.get_concept(target)
        if start is None or end is None:
            return None
        if start.id == end.id:
            return [source]

        visited: set[str] = {start.id}
        queue: deque[tuple[str, List[str]]] = deque([(start.id, [source])])

        while queue:
            current_id, path = queue.popleft()
            if len(path) > max_depth:
                continue
            neighbors = self._get_neighbors(current_id, relation=None)
            for neighbor_id, _rel in neighbors:
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                concept = self.store.get_concept_by_id(neighbor_id)
                if concept is None:
                    continue
                new_path = path + [concept.name]
                if neighbor_id == end.id:
                    return new_path
                queue.append((neighbor_id, new_path))
        return None

    def get_tech_compatibility(self, tech_name: str) -> list:
        """Get all compatibility records for a technology."""
        return self.store.get_compatibility(tech_name)

    def concept_stats(self) -> Dict[str, int]:
        """Count concepts by type and edges by relation."""
        concepts = self.store.list_concepts()
        edges = self.store.query_edges()

        concepts_by_type: Dict[str, int] = {}
        for c in concepts:
            concepts_by_type[c.concept_type] = (
                concepts_by_type.get(c.concept_type, 0) + 1
            )

        edges_by_relation: Dict[str, int] = {}
        for e in edges:
            edges_by_relation[e.relation] = (
                edges_by_relation.get(e.relation, 0) + 1
            )

        return {
            "concepts_by_type": concepts_by_type,
            "edges_by_relation": edges_by_relation,
        }

    # ── Helpers ────────────────────────────────────────────────────────

    def _get_neighbors(
        self, concept_id: str, relation: Optional[str],
    ) -> List[tuple]:
        """Get (neighbor_id, relation) pairs for a concept (bidirectional)."""
        outgoing = self.store.query_edges(
            source_id=concept_id, relation=relation,
        )
        incoming = self.store.query_edges(
            target_id=concept_id, relation=relation,
        )
        neighbors: List[tuple] = []
        for edge in outgoing:
            neighbors.append((edge.target_id, edge.relation))
        for edge in incoming:
            neighbors.append((edge.source_id, edge.relation))
        return neighbors

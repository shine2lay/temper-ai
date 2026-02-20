"""Compiled program store — JSON file persistence for optimized programs."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from temper_ai.optimization.dspy.constants import DEFAULT_PROGRAM_STORE_DIR

logger = logging.getLogger(__name__)


class CompiledProgramStore:
    """Persists compiled DSPy programs as JSON files."""

    def __init__(self, store_dir: str = DEFAULT_PROGRAM_STORE_DIR) -> None:
        self._store_dir = Path(store_dir)

    def save(
        self,
        agent_name: str,
        program: Any,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """Save compiled program data as JSON. Returns program_id."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        program_id = f"{agent_name}_{timestamp}"
        agent_dir = self._store_dir / agent_name
        agent_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "program_id": program_id,
            "agent_name": agent_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
            "program_data": program if isinstance(program, dict) else {},
        }
        file_path = agent_dir / f"{program_id}.json"
        file_path.write_text(json.dumps(payload, indent=2, default=str))
        logger.info("Saved program %s to %s", program_id, file_path)
        return program_id

    def load_latest(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """Load the most recent compiled program for an agent."""
        agent_dir = self._store_dir / agent_name
        if not agent_dir.is_dir():
            return None

        json_files = sorted(
            agent_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not json_files:
            return None

        return self._load_file(json_files[0])

    def load(self, agent_name: str, program_id: str) -> Optional[Dict[str, Any]]:
        """Load a specific compiled program by ID."""
        file_path = self._store_dir / agent_name / f"{program_id}.json"
        if not file_path.is_file():
            return None
        return self._load_file(file_path)

    def list_programs(
        self, agent_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List available compiled programs with metadata."""
        programs: List[Dict[str, Any]] = []
        if agent_name:
            dirs = [self._store_dir / agent_name]
        else:
            dirs = (
                [d for d in self._store_dir.iterdir() if d.is_dir()]
                if self._store_dir.is_dir()
                else []
            )

        for agent_dir in dirs:
            if not agent_dir.is_dir():
                continue
            for json_file in sorted(agent_dir.glob("*.json")):
                data = self._load_file(json_file)
                if data:
                    programs.append({
                        "program_id": data.get("program_id", json_file.stem),
                        "agent_name": data.get("agent_name", agent_dir.name),
                        "created_at": data.get("created_at", ""),
                        "metadata": data.get("metadata", {}),
                    })
        return programs

    @staticmethod
    def _load_file(file_path: Path) -> Optional[Dict[str, Any]]:
        """Load and parse a JSON program file."""
        try:
            data: Dict[str, Any] = json.loads(file_path.read_text())
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load %s: %s", file_path, exc)
            return None

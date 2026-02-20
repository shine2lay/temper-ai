"""Tests for CompiledProgramStore."""

import json
from pathlib import Path

import pytest

from temper_ai.optimization.program_store import CompiledProgramStore


class TestCompiledProgramStore:

    def test_save_creates_file(self, tmp_path):
        store = CompiledProgramStore(store_dir=str(tmp_path))
        program_id = store.save("researcher", {"instruction": "Be thorough"})
        assert program_id.startswith("researcher_")
        files = list((tmp_path / "researcher").glob("*.json"))
        assert len(files) == 1

    def test_save_and_load(self, tmp_path):
        store = CompiledProgramStore(store_dir=str(tmp_path))
        program_id = store.save(
            "researcher",
            {"instruction": "Be thorough"},
            metadata={"optimizer": "bootstrap"},
        )
        loaded = store.load("researcher", program_id)
        assert loaded is not None
        assert loaded["program_id"] == program_id
        assert loaded["agent_name"] == "researcher"
        assert loaded["metadata"]["optimizer"] == "bootstrap"
        assert loaded["program_data"]["instruction"] == "Be thorough"

    def test_load_latest(self, tmp_path):
        store = CompiledProgramStore(store_dir=str(tmp_path))
        store.save("researcher", {"v": 1})
        import time
        time.sleep(0.05)  # intentional delay for mtime ordering
        id2 = store.save("researcher", {"v": 2})
        latest = store.load_latest("researcher")
        assert latest is not None
        assert latest["program_id"] == id2

    def test_load_latest_no_programs(self, tmp_path):
        store = CompiledProgramStore(store_dir=str(tmp_path))
        assert store.load_latest("nonexistent") is None

    def test_load_nonexistent(self, tmp_path):
        store = CompiledProgramStore(store_dir=str(tmp_path))
        assert store.load("researcher", "no-such-id") is None

    def test_list_programs_all(self, tmp_path):
        store = CompiledProgramStore(store_dir=str(tmp_path))
        store.save("agent1", {"v": 1})
        store.save("agent2", {"v": 2})
        programs = store.list_programs()
        assert len(programs) == 2
        names = {p["agent_name"] for p in programs}
        assert names == {"agent1", "agent2"}

    def test_list_programs_filtered(self, tmp_path):
        store = CompiledProgramStore(store_dir=str(tmp_path))
        store.save("agent1", {"v": 1})
        store.save("agent2", {"v": 2})
        programs = store.list_programs(agent_name="agent1")
        assert len(programs) == 1
        assert programs[0]["agent_name"] == "agent1"

    def test_list_programs_empty_dir(self, tmp_path):
        store = CompiledProgramStore(store_dir=str(tmp_path / "empty"))
        programs = store.list_programs()
        assert programs == []

    def test_load_corrupted_json(self, tmp_path):
        agent_dir = tmp_path / "researcher"
        agent_dir.mkdir()
        bad_file = agent_dir / "bad.json"
        bad_file.write_text("not json{{{")
        store = CompiledProgramStore(store_dir=str(tmp_path))
        result = store.load("researcher", "bad")
        assert result is None

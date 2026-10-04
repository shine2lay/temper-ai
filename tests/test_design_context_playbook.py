"""Schema contract for Design's context playbook (queue #37).

configs/design/knowledge/context-playbook.json tells design agents which style families, density,
depth, motion, colour, type and imagery fit a product x page x user context, citing evidence ids.
The file is produced by the Design research base (~/design-lab/research/ui-preferences) and carries
every evidence entry it cites. No model, browser or network.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KNOW = ROOT / "configs/design/knowledge"
PB = json.loads((KNOW / "context-playbook.json").read_text())
EVIDENCE = {e["id"]: e for e in PB["evidence"]}
CONTEXT_FIELDS = {"id", "name", "product", "page", "users", "device", "confidence", "styles", "density",
                  "depth", "motion", "colour", "type", "imagery", "avoid", "trust_signals",
                  "test_with_users", "evidence"}
EVIDENCE_FIELDS = {"id", "question", "claim", "kind", "source", "authors", "year", "venue", "sample_size",
                   "method", "quote_or_number", "url", "grade", "verified"}
IDS = re.compile(r"E\d{3}")


def cited(obj) -> set[str]:
    return set(IDS.findall(json.dumps(obj)))


def test_top_level():
    for key in ("title", "version", "date", "how_to_use", "global_rules", "contexts", "evidence"):
        assert key in PB, key
    assert 15 <= len(PB["contexts"]) <= 30


def test_context_ids_unique_and_slugs():
    ids = [c["id"] for c in PB["contexts"]]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", i) for i in ids)


@pytest.mark.parametrize("ctx", PB["contexts"], ids=lambda c: c["id"])
def test_context_shape_and_citations(ctx):
    assert CONTEXT_FIELDS <= set(ctx), CONTEXT_FIELDS - set(ctx)
    assert ctx["confidence"] in {"high", "medium", "low"}
    assert ctx["styles"]["preferred"], "a context names at least one preferred style family"
    assert isinstance(ctx["avoid"], list) and ctx["avoid"]
    ids = cited(ctx)
    assert len(ids) >= 3
    assert ids <= set(EVIDENCE), ids - set(EVIDENCE)
    assert set(ctx["evidence"]) >= ids, "inline ids are also listed in 'evidence'"
    assert any(EVIDENCE[i]["grade"] in {"A", "B"} for i in ids), "at least one A/B source"


def test_global_rules_cite_known_evidence():
    for rule in PB["global_rules"]:
        assert rule["evidence"] and set(rule["evidence"]) <= set(EVIDENCE)
        assert rule["confidence"] in {"high", "medium", "low"}


def test_evidence_entries():
    assert cited(PB["contexts"]) | cited(PB["global_rules"]) == set(EVIDENCE), "carries exactly what it cites"
    for e in PB["evidence"]:
        assert EVIDENCE_FIELDS <= set(e), (e["id"], EVIDENCE_FIELDS - set(e))
        assert e["grade"] in {"A", "B", "C", "D"}
        assert e["url"].startswith("http")
        assert len(e["quote_or_number"]) <= 400, "short quotes only"
        if e["grade"] in {"A", "B"}:
            assert e["verified"] is True, f"{e['id']}: A/B quotes are re-checked at the source"


def test_markdown_copy_lists_every_context():
    md = (KNOW / "context-playbook.md").read_text()
    for c in PB["contexts"]:
        assert c["name"] in md

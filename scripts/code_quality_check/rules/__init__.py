"""Scanner rules — auto-discovered by the runner.

To add a new rule:
    1. Create a file here (e.g., my_rule.py)
    2. Define a class that subclasses Rule or ExternalToolRule
    3. It's automatically picked up — no registration needed
"""

import importlib
import pkgutil
from pathlib import Path

from scripts.code_quality_check.base import Rule


def discover_rules() -> list[Rule]:
    """Auto-discover all Rule subclasses in this package."""
    rules = []
    package_dir = Path(__file__).parent

    for _, module_name, _ in pkgutil.iter_modules([str(package_dir)]):
        module = importlib.import_module(f"scripts.code_quality_check.rules.{module_name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, Rule)
                and attr is not Rule
                and getattr(attr, "key", "")  # skip abstract bases without key
            ):
                rules.append(attr())

    return sorted(rules, key=lambda r: r.key)

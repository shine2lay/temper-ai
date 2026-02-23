"""Security limits for configuration loading and processing.

This module defines security-related constants to prevent various attacks:
- Memory exhaustion attacks (large configs, env vars)
- Stack overflow attacks (deeply nested YAML)
- Billion laughs attacks (exponential YAML expansion)

All limits are designed to allow legitimate use cases while blocking malicious inputs.
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ConfigSecurityLimits:
    """Security limits for configuration file processing.

    These limits protect against:
    - Memory exhaustion from malicious config files
    - Stack overflow from deeply nested YAML structures
    - Billion laughs attacks (exponential entity expansion)
    - DoS attacks via environment variable expansion
    """

    # Maximum config file size (10MB) to prevent memory exhaustion
    # Rationale: Legitimate configs are typically <1MB. 10MB provides headroom
    # for large multi-agent workflows while preventing memory exhaustion.
    MAX_CONFIG_SIZE: Final[int] = 10 * 1024 * 1024  # 10MB

    # Maximum environment variable value length (10KB) to prevent DoS attacks
    # Rationale: Most legitimate env vars are <1KB. 10KB allows for large JWTs/keys
    # while preventing memory exhaustion from ${VAR} expansion attacks.
    MAX_ENV_VAR_SIZE: Final[int] = 10 * 1024  # 10KB

    # Maximum YAML nesting depth to prevent stack overflow and YAML bombs
    # Rationale: Legitimate configs rarely exceed 20 levels. 50 provides safety margin.
    # Prevents stack overflow from deeply nested structures like:
    #   a: { b: { c: { ... } } }  (50+ levels deep)
    MAX_YAML_NESTING_DEPTH: Final[int] = 50

    # Maximum number of YAML nodes to prevent billion laughs attacks
    # Rationale: Most configs have <1000 nodes. 100,000 allows large configs while
    # preventing exponential expansion attacks (billion laughs can create billions of nodes).
    # Example attack:
    #   lol: &lol ["lol"]
    #   lol2: &lol2 [*lol, *lol, *lol, *lol, *lol, *lol, *lol, *lol, *lol]
    #   lol3: &lol3 [*lol2, *lol2, *lol2, *lol2, *lol2, *lol2, *lol2, *lol2]
    #   (continues exponentially, creating billions of nodes)
    MAX_YAML_NODES: Final[int] = 100_000


# Singleton instance for easy importing
CONFIG_SECURITY: Final = ConfigSecurityLimits()

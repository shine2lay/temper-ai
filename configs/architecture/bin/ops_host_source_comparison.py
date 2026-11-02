"""Compatibility facade. Canonical objects live only in p3_source_closure.

Delivery requires the reviewed p3_source_closure package in the normal Python
installation. This module does not repair sys.path or load an alias copy.
"""

from p3_source_closure import *  # noqa: F403 -- exactly the canonical public API
from p3_source_closure import __all__ as __all__

"""Foundation design workflow (design_foundation_v1): workspace, closed contracts, brief reader, and stubs."""
from __future__ import annotations

from .brief import BRIEF_SECTIONS, BriefError
from .contracts import (
    BRIEF_SCHEMA,
    DESIGN_MD_SECTIONS,
    DIRECTION_SUBSECTIONS,
    MODEL_STEPS,
    STEP_INPUTS,
    TOKEN_PARTS,
    TOKENS_SCHEMA,
    ContractError,
    check_input,
    check_read,
    validate,
    validate_design_md,
    validate_tokens,
)
from .workspace import FOLDERS, STAGES, STEPS, Workspace, WorkspaceError

__all__ = [
    "BRIEF_SCHEMA",
    "BRIEF_SECTIONS",
    "BriefError",
    "ContractError",
    "DESIGN_MD_SECTIONS",
    "DIRECTION_SUBSECTIONS",
    "FOLDERS",
    "MODEL_STEPS",
    "STAGES",
    "STEPS",
    "STEP_INPUTS",
    "TOKENS_SCHEMA",
    "TOKEN_PARTS",
    "Workspace",
    "WorkspaceError",
    "check_input",
    "check_read",
    "validate",
    "validate_design_md",
    "validate_tokens",
]

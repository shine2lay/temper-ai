"""Constants for DAG visualization."""

# Mermaid styling
MERMAID_DIRECTION = "TD"
MERMAID_ROOT_STYLE = "fill:#2ecc71,stroke:#27ae60,color:#fff"
MERMAID_TERMINAL_STYLE = "fill:#3498db,stroke:#2980b9,color:#fff"
MERMAID_NODE_SHAPE_START = "["
MERMAID_NODE_SHAPE_END = "]"

# ASCII tree
ASCII_BRANCH = "├── "
ASCII_LAST = "└── "
ASCII_PIPE = "│   "
ASCII_SPACE = "    "
ASCII_ARROW = " → "

# DOT defaults
DOT_RANKDIR = "TB"
DOT_NODE_SHAPE = "box"
DOT_ROOT_COLOR = "#2ecc71"
DOT_TERMINAL_COLOR = "#3498db"

# Format choices
FORMAT_ASCII = "ascii"
FORMAT_MERMAID = "mermaid"
FORMAT_DOT = "dot"

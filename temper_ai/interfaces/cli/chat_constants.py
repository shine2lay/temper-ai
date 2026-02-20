"""Constants for interactive chat mode (R0.4)."""

CHAT_EXIT_COMMANDS = frozenset({"exit", "quit", "bye", "/exit", "/quit"})
CHAT_HELP_COMMANDS = frozenset({"help", "/help"})
CHAT_CLEAR_COMMAND = "/clear"
CHAT_PROMPT_MARKER = "You > "
CHAT_RESPONSE_PREFIX = "Agent"
CHAT_WELCOME_MESSAGE = "Interactive chat with agent '{agent_name}'. Type 'exit' to quit."
CHAT_HELP_TEXT = (
    "Commands:\n"
    "  exit, quit, bye  — End the chat session\n"
    "  /clear           — Clear conversation history\n"
    "  /help            — Show this help message\n"
)
MAX_CHAT_HISTORY_TURNS = 50

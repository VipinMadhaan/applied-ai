"""Chat feature: factory for creating AI chat sessions.

Satisfies specs/chat.md (src/features/chat.py component).
"""

from src.ai.openai_client import ChatSession


def fun_create_session(account_id: int, username: str) -> ChatSession:
    """Return a new ChatSession scoped to the given account.

    The returned session maintains conversation memory across calls and
    validates every LLM-generated SQL query before execution.
    Satisfies specs/chat.md AC-2 through AC-8.

    Args:
        account_id: Primary key of the authenticated user's bank account.
        username:   The user's display name, shown in the system prompt.

    Returns:
        ChatSession: A ready-to-use chat session instance.
    """
    return ChatSession(account_id=account_id, username=username)

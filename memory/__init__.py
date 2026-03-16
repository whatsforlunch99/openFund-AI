"""Memory package: situation memory (global) and user memory (per-user).

Situation memory: global knowledge base of (situation, recommendation) pairs with
BM25 retrieval; one app-wide store; file memory_store_path/situation_memory.json.
Use for lookup by similarity (e.g. "inflation concerns" -> recommendations).

User memory: per-user working memory and preference labels for planner context;
500-word cap with optional compression; file memory_store_path/<user_id>/user_memory.json.
Used by API/planner for personalization; appended when conversations complete.
"""

# Situation memory: global singleton, BM25 retrieval
from memory.situation_memory import (
    SITUATION_MEMORY_FILENAME,
    FinancialSituationMemory,
    get_situation_memory,
)
# User memory: per-user blob + preference labels, planner context
from memory.user_memory import (
    append_preference_labels,
    append_user_memory,
    compress_to_gist,
    get_user_memory,
    get_user_memory_raw,
    set_compressor,
    update_preference_labels,
)

__all__ = [
    "FinancialSituationMemory",
    "get_situation_memory",
    "SITUATION_MEMORY_FILENAME",
    "get_user_memory",
    "get_user_memory_raw",
    "append_user_memory",
    "update_preference_labels",
    "append_preference_labels",
    "set_compressor",
    "compress_to_gist",
]

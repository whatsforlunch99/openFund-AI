"""Financial situation memory using BM25 for lexical similarity matching.

Uses BM25 (Best Matching 25) for retrieval — no API calls, no token limits,
works offline. Supports save/load for persistence under MEMORY_STORE_PATH.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

# Default filename under MEMORY_STORE_PATH
SITUATION_MEMORY_FILENAME = "situation_memory.json"

_situation_memory_instance: FinancialSituationMemory | None = None


def get_situation_memory(memory_store_path: str = "memory") -> FinancialSituationMemory:
    """Return the shared situation memory, loading from disk if present.

    Args:
        memory_store_path: Root directory (e.g. MEMORY_STORE_PATH). Default "memory".

    Returns:
        Singleton FinancialSituationMemory instance.
    """
    global _situation_memory_instance
    # Lazy init: create singleton and load from disk if file exists
    if _situation_memory_instance is None:
        _situation_memory_instance = FinancialSituationMemory("openfund")
        _situation_memory_instance.load_from_dir(memory_store_path)
    return _situation_memory_instance


class FinancialSituationMemory:
    """Memory for (situation, recommendation) pairs with BM25 retrieval."""

    def __init__(
        self,
        name: str = "default",
        _config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the memory. _config is reserved for API compatibility and is unused.

        Args:
            name: Instance name (e.g. "default", "openfund").
            _config: Reserved; unused.
        """
        self.name = name
        self.documents: list[str] = []
        self.recommendations: list[str] = []
        self._bm25: BM25Okapi | None = None

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"\b\w+\b", text.lower())
        return tokens

    def _rebuild_index(self) -> None:
        # Tokenize all documents and build BM25 index for similarity search
        if self.documents:
            tokenized = [self._tokenize(d) for d in self.documents]
            self._bm25 = BM25Okapi(tokenized)
        else:
            self._bm25 = None

    def add_situations(self, situations_and_advice: list[tuple[str, str]]) -> None:
        """Add (situation, recommendation) pairs and rebuild the BM25 index.

        Args:
            situations_and_advice: List of (situation_text, recommendation_text) tuples.
        """
        for situation, recommendation in situations_and_advice:
            self.documents.append(situation)
            self.recommendations.append(recommendation)
        self._rebuild_index()

    def get_memories(
        self, current_situation: str, n_matches: int = 1
    ) -> list[dict[str, Any]]:
        """Return top-n BM25 matches for the current situation.

        Args:
            current_situation: Query text to match.
            n_matches: Number of top matches to return. Default 1.

        Returns:
            List of dicts with matched_situation, recommendation, similarity_score.
        """
        if not self.documents or self._bm25 is None:
            return []

        query_tokens = self._tokenize(current_situation)
        scores = self._bm25.get_scores(query_tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
            :n_matches
        ]
        # Normalize scores to [0, 1] and build result dicts with situation and recommendation
        max_score = max(scores) if max(scores) > 0 else 1.0
        results = []
        for idx in top_indices:
            norm = scores[idx] / max_score if max_score > 0 else 0.0
            results.append(
                {
                    "matched_situation": self.documents[idx],
                    "recommendation": self.recommendations[idx],
                    "similarity_score": norm,
                }
            )
        return results

    def clear(self) -> None:
        """Clear all stored situations and recommendations."""
        self.documents = []
        self.recommendations = []
        self._bm25 = None

    def save(self, path: str | os.PathLike[str]) -> None:
        """Persist (situation, recommendation) pairs to a JSON file.

        Args:
            path: Output file path. Parent directories are created if needed.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {"situation": s, "recommendation": r}
            for s, r in zip(self.documents, self.recommendations)
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load(self, path: str | os.PathLike[str]) -> None:
        """Load pairs from JSON and rebuild BM25 index.

        Args:
            path: JSON file path. No-op if file does not exist.
        """
        path = Path(path)
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.documents = []
        self.recommendations = []
        for item in data:
            s = item.get("situation", "")
            r = item.get("recommendation", "")
            self.documents.append(s)
            self.recommendations.append(r)
        self._rebuild_index()

    def load_from_dir(self, memory_store_path: str) -> None:
        """Load from memory_store_path/situation_memory.json if present.

        Args:
            memory_store_path: Root directory (e.g. MEMORY_STORE_PATH).
        """
        root = Path(memory_store_path).expanduser().resolve()
        path = root / SITUATION_MEMORY_FILENAME
        self.load(path)

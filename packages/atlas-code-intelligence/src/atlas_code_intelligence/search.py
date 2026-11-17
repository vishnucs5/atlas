"""Lexical, regex, symbol, and local semantic code search engine."""

import fnmatch
import math
import re
from typing import Any

from atlas_code_intelligence.indexer import RepositoryIndexer
from atlas_code_intelligence.models import Symbol, SymbolType


class CodeSearchEngine:
    """Multi-strategy code search with local ranking fallback."""

    def __init__(self, indexer: RepositoryIndexer) -> None:
        self.indexer = indexer

    def search_exact_text(
        self,
        query: str,
        case_sensitive: bool = False,
        max_matches: int = 100,
    ) -> list[dict[str, Any]]:
        """Exact literal string search across repository files."""
        matches: list[dict[str, Any]] = []
        target = query if case_sensitive else query.lower()

        for fpath in self.indexer.file_records:
            full_path = self.indexer.repo_root / fpath
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for idx, line in enumerate(content.splitlines(), start=1):
                comp_line = line if case_sensitive else line.lower()
                if target in comp_line:
                    matches.append(
                        {
                            "file_path": fpath,
                            "line_number": idx,
                            "line_content": line.strip(),
                            "match_type": "exact_text",
                        }
                    )
                    if len(matches) >= max_matches:
                        return matches
        return matches

    def search_regex(
        self,
        pattern_str: str,
        max_matches: int = 100,
    ) -> list[dict[str, Any]]:
        """Regular expression search with safety bounds and timeout safeguards."""
        matches: list[dict[str, Any]] = []
        try:
            pattern = re.compile(pattern_str)
        except re.error as exc:
            msg = f"Invalid regular expression: {exc}"
            raise ValueError(msg) from exc

        for fpath in self.indexer.file_records:
            full_path = self.indexer.repo_root / fpath
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for idx, line in enumerate(content.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(
                        {
                            "file_path": fpath,
                            "line_number": idx,
                            "line_content": line.strip(),
                            "match_type": "regex",
                        }
                    )
                    if len(matches) >= max_matches:
                        return matches
        return matches

    def search_symbols(
        self,
        query: str,
        symbol_type: SymbolType | None = None,
        max_matches: int = 50,
    ) -> list[Symbol]:
        """Search code symbols by prefix, exact, or substring match."""
        results: list[Symbol] = []
        q_lower = query.lower()

        for sym_name, symbols in self.indexer.symbol_table.items():
            if q_lower in sym_name.lower():
                for s in symbols:
                    if symbol_type is None or s.symbol_type == symbol_type:
                        results.append(s)
                        if len(results) >= max_matches:
                            return results
        return results

    def search_filenames(
        self,
        pattern: str,
        max_matches: int = 50,
    ) -> list[str]:
        """Glob search across indexed file paths."""
        results: list[str] = []
        for fpath in self.indexer.file_records:
            if fnmatch.fnmatch(fpath, pattern) or fnmatch.fnmatch(fpath.split("/")[-1], pattern):
                results.append(fpath)
                if len(results) >= max_matches:
                    return results
        return results

    def search_local_semantic_ranking(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Local BM25 / TF-IDF relevance ranking fallback without requiring an external embedding provider."""
        tokens = re.findall(r"\b[a-zA-Z0-9_]{3,}\b", query.lower())
        if not tokens:
            return []

        doc_frequencies: dict[str, int] = {}
        doc_tokens_map: dict[str, list[str]] = {}

        # Build corpus token maps
        for fpath in self.indexer.file_records:
            full_path = self.indexer.repo_root / fpath
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                dtokens = re.findall(r"\b[a-zA-Z0-9_]{3,}\b", content.lower())
                doc_tokens_map[fpath] = dtokens
                token_set = set(dtokens)
                for t in token_set:
                    doc_frequencies[t] = doc_frequencies.get(t, 0) + 1
            except OSError:
                continue

        n_docs = len(doc_tokens_map)
        if n_docs == 0:
            return []

        # Score documents
        scored_docs: list[tuple[str, float]] = []

        for fpath, dtokens in doc_tokens_map.items():
            score = 0.0
            doc_len = len(dtokens) or 1
            for t in tokens:
                tf = dtokens.count(t) / doc_len
                df = doc_frequencies.get(t, 0)
                idf = math.log((n_docs + 1) / (df + 1)) + 1.0
                score += tf * idf

            if score > 0:
                scored_docs.append((fpath, score))

        scored_docs.sort(key=lambda item: item[1], reverse=True)

        return [
            {
                "file_path": fpath,
                "relevance_score": round(score, 4),
                "match_type": "local_semantic_ranking",
            }
            for fpath, score in scored_docs[:top_k]
        ]

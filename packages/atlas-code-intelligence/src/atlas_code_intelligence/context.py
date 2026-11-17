"""Evidence-based context assembler with security guardrails and provenance tracking."""

import re
from datetime import UTC, datetime

from atlas_code_intelligence.graph import DependencyGraph
from atlas_code_intelligence.indexer import RepositoryIndexer
from atlas_code_intelligence.models import ContextAssembly, ContextItem
from atlas_code_intelligence.search import CodeSearchEngine

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+(?:an?\s+)?unrestricted\b"),
    re.compile(r"(?i)\bsystem\s+override\s*:\b"),
    re.compile(r"(?i)\bexecute\s+arbitrary\s+(?:shell|command)\b"),
    re.compile(r"(?i)\bbypass\s+action\s+firewall\b"),
]


class ContextAssembler:
    """Assembles minimal, evidence-backed code context for model prompts with strict security boundaries."""

    def __init__(
        self,
        indexer: RepositoryIndexer,
        graph: DependencyGraph | None = None,
        search_engine: CodeSearchEngine | None = None,
        max_total_tokens: int = 8000,
    ) -> None:
        self.indexer = indexer
        self.graph = graph or DependencyGraph(indexer)
        self.search = search_engine or CodeSearchEngine(indexer)
        self.max_total_tokens = max_total_tokens

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count based on standard character-to-token ratio (~4 chars per token)."""
        return max(1, len(text) // 4)

    @staticmethod
    def sanitize_untrusted_content(text: str) -> tuple[str, list[str]]:
        """Sanitize prompt injection attempts and warn on malicious comments."""
        warnings: list[str] = []
        sanitized = text

        for pattern in PROMPT_INJECTION_PATTERNS:
            if pattern.search(sanitized):
                warnings.append(f"Prompt injection pattern detected: '{pattern.pattern}'")
                sanitized = pattern.sub("[POTENTIAL_PROMPT_INJECTION_FILTERED]", sanitized)

        return sanitized, warnings

    def assemble_context(
        self,
        objective: str,
        target_files: list[str] | None = None,
        max_file_lines: int = 150,
    ) -> ContextAssembly:
        """Synthesize an evidence-based context assembly for a coding objective."""
        items: list[ContextItem] = []
        provenance_notes: list[str] = []
        total_tokens = 0
        included_files: set[str] = set()

        # Step 1: Explicit target files
        if target_files:
            for tf in target_files:
                if tf in self.indexer.file_records and tf not in included_files:
                    item = self._build_context_item(
                        tf,
                        selection_reason=f"Explicit target file for objective '{objective}'",
                        base_relevance=1.0,
                        max_lines=max_file_lines,
                    )
                    if item and (total_tokens + item.estimated_tokens <= self.max_total_tokens):
                        items.append(item)
                        included_files.add(tf)
                        total_tokens += item.estimated_tokens
                        provenance_notes.append(f"Added explicit target: {tf}")

        # Step 2: Symbol Lookups matching query
        words = re.findall(r"\b[a-zA-Z0-9_]{3,}\b", objective)
        for w in words:
            symbols = self.graph.lookup_symbol(w)
            for sym in symbols:
                if sym.file_path not in included_files:
                    item = self._build_context_item(
                        sym.file_path,
                        selection_reason=f"Matches symbol definition '{sym.name}' ({sym.symbol_type.value})",
                        base_relevance=0.85,
                        max_lines=max_file_lines,
                    )
                    if item and (total_tokens + item.estimated_tokens <= self.max_total_tokens):
                        items.append(item)
                        included_files.add(sym.file_path)
                        total_tokens += item.estimated_tokens
                        provenance_notes.append(
                            f"Added symbol definition: {sym.name} in {sym.file_path}"
                        )

        # Step 3: Semantic Ranking Search
        ranked = self.search.search_local_semantic_ranking(objective, top_k=5)
        for r in ranked:
            fpath = r["file_path"]
            if fpath not in included_files:
                item = self._build_context_item(
                    fpath,
                    selection_reason=f"Semantic ranking match (score: {r['relevance_score']})",
                    base_relevance=float(r["relevance_score"]),
                    max_lines=max_file_lines,
                )
                if item and (total_tokens + item.estimated_tokens <= self.max_total_tokens):
                    items.append(item)
                    included_files.add(fpath)
                    total_tokens += item.estimated_tokens
                    provenance_notes.append(f"Added semantically ranked file: {fpath}")

        # Step 4: Include associated test files for selected sources
        current_sources = list(included_files)
        for sf in current_sources:
            test_files = self.graph.find_test_files_for_source(sf)
            for tf in test_files:
                if tf not in included_files:
                    item = self._build_context_item(
                        tf,
                        selection_reason=f"Associated test suite for source '{sf}'",
                        base_relevance=0.75,
                        max_lines=max_file_lines,
                    )
                    if item and (total_tokens + item.estimated_tokens <= self.max_total_tokens):
                        items.append(item)
                        included_files.add(tf)
                        total_tokens += item.estimated_tokens
                        provenance_notes.append(f"Added associated test: {tf}")

        return ContextAssembly(
            query=objective,
            items=items,
            total_estimated_tokens=total_tokens,
            assembled_at=datetime.now(UTC),
            provenance_notes=provenance_notes,
        )

    def _build_context_item(
        self,
        file_path: str,
        selection_reason: str,
        base_relevance: float,
        max_lines: int = 150,
    ) -> ContextItem | None:
        """Construct an individual ContextItem with hash and security sanitization."""
        full_path = self.indexer.repo_root / file_path
        if not full_path.is_file():
            return None

        # Exclude secrets and binary files strictly
        if self.indexer.explorer.is_sensitive(file_path):
            return None

        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        lines = content.splitlines(keepends=True)
        bounded_content = "".join(lines[:max_lines])
        if len(lines) > max_lines:
            bounded_content += f"\n... [Truncated: {len(lines) - max_lines} lines omitted] ...\n"

        # Sanitize untrusted content
        sanitized_content, warnings = self.sanitize_untrusted_content(bounded_content)
        if warnings:
            selection_reason += f" [SECURITY WARNING: {'; '.join(warnings)}]"

        c_hash = (
            self.indexer.file_records[file_path].sha256
            if file_path in self.indexer.file_records
            else ""
        )
        tokens = self.estimate_tokens(sanitized_content)

        return ContextItem(
            file_path=file_path,
            relevance_score=base_relevance,
            selection_reason=selection_reason,
            content_snippet=sanitized_content,
            line_range=(1, min(len(lines), max_lines)),
            content_hash=c_hash,
            index_version=self.indexer.index_version,
            estimated_tokens=tokens,
            is_untrusted_repository_content=True,
        )

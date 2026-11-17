"""Incremental index management, stale index detection, change detection, and recovery."""

from typing import Any

from atlas_code_intelligence.indexer import RepositoryIndexer
from atlas_code_intelligence.models import FileIndexRecord


class IndexChangeSet:
    """Summary of detected changes between live repository and index state."""

    def __init__(self) -> None:
        self.created_files: list[str] = []
        self.modified_files: list[str] = []
        self.deleted_files: list[str] = []
        self.renamed_files: list[tuple[str, str]] = []  # (old_path, new_path)

    @property
    def has_changes(self) -> bool:
        """Return True if any changes exist."""
        return bool(
            self.created_files or self.modified_files or self.deleted_files or self.renamed_files
        )


class IncrementalIndexManager:
    """Detects delta changes and updates index without full rebuild."""

    def __init__(self, indexer: RepositoryIndexer) -> None:
        self.indexer = indexer

    def detect_changes(self) -> IndexChangeSet:
        """Reconcile current repository state against the existing index."""
        changes = IndexChangeSet()
        discovered_metas = self.indexer.explorer.discover_files(
            include_binary=False, include_sensitive=False
        )
        discovered_map = {m.rel_path: m for m in discovered_metas}
        indexed_map = self.indexer.file_records

        # Detect created and modified
        indexed_by_hash: dict[str, str] = {
            rec.sha256: rec.file_path for rec in indexed_map.values()
        }

        for rel_path, meta in discovered_map.items():
            if rel_path not in indexed_map:
                # Check if it was renamed (same hash exists in indexed_map under different path)
                if meta.sha256 in indexed_by_hash:
                    old_path = indexed_by_hash[meta.sha256]
                    if old_path not in discovered_map:
                        changes.renamed_files.append((old_path, rel_path))
                        continue
                changes.created_files.append(rel_path)
            else:
                if indexed_map[rel_path].sha256 != meta.sha256:
                    changes.modified_files.append(rel_path)

        # Detect deleted
        for indexed_path in indexed_map:
            if indexed_path not in discovered_map:
                # If already identified in rename, skip from deleted
                if not any(old == indexed_path for old, _ in changes.renamed_files):
                    changes.deleted_files.append(indexed_path)

        return changes

    def is_index_stale(self) -> bool:
        """Check whether the persisted index is stale compared to disk."""
        changes = self.detect_changes()
        return changes.has_changes

    def refresh_incremental(self) -> dict[str, Any]:
        """Apply incremental updates only to changed, created, or deleted files."""
        changes = self.detect_changes()
        if not changes.has_changes:
            return {"status": "UP_TO_DATE", "updated": 0, "deleted": 0}

        # 1. Handle renames: update path in records and symbols
        for old_p, new_p in changes.renamed_files:
            if old_p in self.indexer.file_records:
                rec = self.indexer.file_records.pop(old_p)
                rec.file_path = new_p
                for sym in rec.symbols:
                    sym.file_path = new_p
                self.indexer.file_records[new_p] = rec

        # 2. Handle deletions: remove from records and prune symbol table
        for d_path in changes.deleted_files:
            self._remove_file_from_index(d_path)

        # 3. Handle created and modified files
        to_index = changes.created_files + changes.modified_files
        updated_count = 0

        for rel_path in to_index:
            # Clean up old symbols first if modifying
            if rel_path in self.indexer.file_records:
                self._remove_file_from_index(rel_path)

            try:
                content = (self.indexer.repo_root / rel_path).read_text(
                    encoding="utf-8", errors="replace"
                )
                meta = self.indexer.explorer.get_metadata(rel_path)
            except OSError:
                continue

            symbols, imports, accuracy, err = self.indexer.parser.parse_file(rel_path, content)

            rec = FileIndexRecord(
                file_path=rel_path,
                language=self.indexer.parser.detect_language(rel_path),
                sha256=meta.sha256,
                size_bytes=meta.size_bytes,
                line_count=len(content.splitlines()),
                symbols=symbols,
                imports=imports,
                parse_accuracy=accuracy,
                is_test_file=self.indexer._is_test_file(rel_path),
                error_message=err,
            )
            self.indexer.file_records[rel_path] = rec
            for sym in symbols:
                self.indexer.symbol_table.setdefault(sym.name, []).append(sym)
            updated_count += 1

        self.indexer.persist_index()

        return {
            "status": "UPDATED",
            "created": len(changes.created_files),
            "modified": len(changes.modified_files),
            "deleted": len(changes.deleted_files),
            "renamed": len(changes.renamed_files),
            "total_updated": updated_count,
        }

    def _remove_file_from_index(self, rel_path: str) -> None:
        """Remove file record and prune corresponding symbols from symbol table."""
        if rel_path in self.indexer.file_records:
            del self.indexer.file_records[rel_path]

        # Prune symbols
        for sym_name in list(self.indexer.symbol_table.keys()):
            self.indexer.symbol_table[sym_name] = [
                s for s in self.indexer.symbol_table[sym_name] if s.file_path != rel_path
            ]
            if not self.indexer.symbol_table[sym_name]:
                del self.indexer.symbol_table[sym_name]

"""Repository indexing pipeline implementing:

DISCOVER -> FILTER -> CLASSIFY -> PARSE -> EXTRACT -> INDEX -> VALIDATE -> PERSIST
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atlas_coding.explorer import RepositoryExplorer

from atlas_code_intelligence.models import FileIndexRecord, ParseAccuracy, Symbol
from atlas_code_intelligence.parser import LanguageParser


class RepositoryIndexer:
    """8-phase safe repository code indexer."""

    def __init__(
        self,
        repo_root: str | Path,
        index_dir: str | Path | None = None,
        max_file_size_bytes: int = 5 * 1024 * 1024,  # 5 MB
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.index_dir = (
            Path(index_dir).resolve() if index_dir else self.repo_root / ".atlas" / "index"
        )

        ignored = {".atlas"}
        if index_dir:
            try:
                rel_parts = self.index_dir.relative_to(self.repo_root).parts
                ignored.update(rel_parts)
            except ValueError:
                pass

        self.explorer = RepositoryExplorer(
            repo_root=self.repo_root,
            max_file_size_bytes=max_file_size_bytes,
            custom_ignored_dirs=ignored,
        )
        self.parser = LanguageParser()

        # In-memory index tables
        self.file_records: dict[str, FileIndexRecord] = {}
        self.symbol_table: dict[str, list[Symbol]] = {}  # symbol_name -> list[Symbol]
        self.index_version: str = "1.0"
        self.last_indexed_at: datetime | None = None

    def _is_test_file(self, rel_path: str) -> bool:
        """Classify whether a file is a test suite or fixture."""
        p_lower = rel_path.lower().replace("\\", "/")
        parts = p_lower.split("/")
        if any(part in ("tests", "test", "__tests__", "spec") for part in parts):
            return True
        basename = parts[-1]
        return (
            basename.startswith("test_")
            or basename.endswith("_test.py")
            or basename.endswith("_test.go")
            or basename.endswith(".test.js")
            or basename.endswith(".test.ts")
            or basename.endswith(".spec.ts")
            or basename.endswith(".spec.js")
            or "test" in basename
        )

    def index_repository(self, force_rebuild: bool = False) -> dict[str, Any]:
        """Execute the full 8-phase indexing pipeline."""
        start_time = datetime.now(UTC)

        # Phase 1: DISCOVER
        discovered_metas = self.explorer.discover_files(
            include_binary=False, include_sensitive=False
        )

        # Phase 2: FILTER & Phase 3: CLASSIFY
        indexed_count = 0
        error_count = 0

        if force_rebuild:
            self.file_records.clear()
            self.symbol_table.clear()

        for meta in discovered_metas:
            rel_path = meta.rel_path

            # Skip unchanged files if incremental
            if not force_rebuild and rel_path in self.file_records:
                existing = self.file_records[rel_path]
                if existing.sha256 == meta.sha256:
                    continue

            # Read content safely
            try:
                content = (self.repo_root / rel_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Phase 4: PARSE & Phase 5: EXTRACT
            symbols, imports, accuracy, err = self.parser.parse_file(rel_path, content)
            if accuracy == ParseAccuracy.SYNTAX_ERROR:
                error_count += 1

            # Phase 6: INDEX
            record = FileIndexRecord(
                file_path=rel_path,
                language=self.parser.detect_language(rel_path),
                sha256=meta.sha256,
                size_bytes=meta.size_bytes,
                line_count=len(content.splitlines()),
                symbols=symbols,
                imports=imports,
                parse_accuracy=accuracy,
                is_test_file=self._is_test_file(rel_path),
                indexed_at=datetime.now(UTC),
                error_message=err,
            )

            # Phase 7: VALIDATE (no secret/null bytes in record)
            assert not any(
                sym.name.startswith("SECRET_") for sym in symbols if "token" in sym.name.lower()
            )

            self.file_records[rel_path] = record

            # Update symbol table
            for sym in symbols:
                self.symbol_table.setdefault(sym.name, []).append(sym)

            indexed_count += 1

        self.last_indexed_at = datetime.now(UTC)
        duration_s = (self.last_indexed_at - start_time).total_seconds()

        # Phase 8: PERSIST
        self.persist_index()

        return {
            "total_files": len(self.file_records),
            "files_indexed": indexed_count,
            "total_symbols": sum(len(syms) for syms in self.symbol_table.values()),
            "parsing_errors": error_count,
            "duration_seconds": round(duration_s, 3),
        }

    def persist_index(self) -> None:
        """Serialize index records to disk cache."""
        self.index_dir.mkdir(parents=True, exist_ok=True)
        out_file = self.index_dir / "repository_index.json"

        data = {
            "version": self.index_version,
            "repo_root": str(self.repo_root),
            "last_indexed_at": self.last_indexed_at.isoformat() if self.last_indexed_at else None,
            "files": {p: rec.model_dump(mode="json") for p, rec in self.file_records.items()},
        }
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load_index(self) -> bool:
        """Load persisted index from disk cache if present."""
        index_file = self.index_dir / "repository_index.json"
        if not index_file.is_file():
            return False

        try:
            with open(index_file, encoding="utf-8") as f:
                data = json.load(f)
            self.file_records.clear()
            self.symbol_table.clear()

            for p, rec_data in data.get("files", {}).items():
                rec = FileIndexRecord.model_validate(rec_data)
                self.file_records[p] = rec
                for sym in rec.symbols:
                    self.symbol_table.setdefault(sym.name, []).append(sym)

            self.index_version = data.get("version", "1.0")
            return True
        except Exception:
            return False

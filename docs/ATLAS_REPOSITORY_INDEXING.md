# ATLAS Repository Indexing Pipeline

## 1. The 8-Phase Indexing Pipeline

ATLAS Code Intelligence implements a deterministic, multi-phase repository indexing lifecycle:

```
[DISCOVER]
    │
    ▼
[FILTER]
    │
    ▼
[CLASSIFY]
    │
    ▼
[PARSE]
    │
    ▼
[EXTRACT]
    │
    ▼
[INDEX]
    │
    ▼
[VALIDATE]
    │
    ▼
[PERSIST]
```

### Phase Details

1. **DISCOVER**:
   Recursively enumerates all files within the repository boundary using `RepositoryExplorer`. Strictly prevents symlink traversal or parent directory escapes outside the repository root.
2. **FILTER**:
   Excludes:
   - Builtin ignored directories: `.git`, `.atlas`, `node_modules`, `__pycache__`, `.venv`, `.pytest_cache`, `dist`, `build`.
   - Sensitive security files: `.env`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `*service_account*.json`, `secrets.*`.
   - Binary files exceeding the 8KB null-byte heuristic threshold.
   - Files exceeding the maximum file size boundary (default 5 MB).
   - Ignored files defined in repository-root `.gitignore`.
3. **CLASSIFY**:
   Identifies programming language based on file extension and path conventions (e.g. `.py` -> Python, `.ts` -> TypeScript, `.go` -> Go, `.rs` -> Rust).
   Categorizes files as source vs. test suites (`_test.py`, `test_*.py`, `.test.ts`, `.spec.ts`, etc.).
4. **PARSE**:
   Executes language-specific parsers. For Python, employs native standard-library `ast` parsing. On syntax errors or non-Python code, uses resilient structural regex heuristics while explicitly setting `ParseAccuracy`.
5. **EXTRACT**:
   Extracts top-level and nested code symbols:
   - Functions / Methods (with line range, signature, docstring preview)
   - Classes / Structs / Interfaces
   - Module imports (direct, aliased, and relative imports)
6. **INDEX**:
   Populates fast in-memory query indexes:
   - File records index (`dict[str, FileIndexRecord]`)
   - Global symbol table (`dict[str, list[Symbol]]`)
7. **VALIDATE**:
   Executes security and integrity invariants:
   - Verifies no sensitive secret tokens are captured in symbol names.
   - Validates symbol line ranges are within document bounds.
   - Asserts non-null file hashes.
8. **PERSIST**:
   Serializes the complete index to `.atlas/index/repository_index.json` with schema versioning (`1.0`) and timestamps. Allows instant cold-start index restoration.

---

## 2. Incremental Indexing and Change Reconciliation

To support large enterprise repositories without redundant re-indexing, `IncrementalIndexManager` detects deltas via SHA-256 hashes:

- **Created Files**: Files present on disk but absent in the index.
- **Modified Files**: Files where the disk SHA-256 differs from the indexed SHA-256.
- **Deleted Files**: Files present in the index but removed from disk.
- **Renamed Files**: Files where a previous path was removed and a new path added with an identical SHA-256 hash.

### Pruning and Symbol Table Cleanup

When a file is modified, deleted, or renamed:
1. Existing symbols registered to the previous path are systematically pruned from `symbol_table`.
2. Empty symbol entries are deleted to prevent stale or zombie symbol lookups.
3. Updated symbols are re-extracted and registered under the new file record.
4. The persisted cache file is atomically updated.

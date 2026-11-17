# ATLAS CLI — Structured Patch Engine & Transactional Rollback

## 1. Overview

The ATLAS Patch Engine (`atlas_coding.patch`) provides robust, transactional application of unified diffs across multi-file codebases.

Rather than relying on external `patch` binaries or unvalidated regex replacements, the ATLAS Patch Engine parses standard unified diff syntax, validates all hunks in memory against current file content, and guarantees atomic execution with automatic rollback upon conflict.

---

## 2. Architecture & Data Model

The patch engine is structured around three core domain models:

- **`UnifiedDiff`**: Represents a multi-file diff containing zero or more `FilePatch` objects, aggregate insertion/deletion metrics, and raw diff text.
- **`FilePatch`**: Represents changes to a specific file, including `source_path`, `target_path`, `is_new`, `is_deleted`, and ordered `hunks`.
- **`PatchHunk`**: A single contiguous edit containing `old_start`, `old_lines`, `new_start`, `new_lines`, and individual hunk lines (` `, `+`, `-`).

```
UnifiedDiff
   ├── FilePatch (src/main.py)
   │      ├── PatchHunk #1 (@@ -1,5 +1,6 @@)
   │      └── PatchHunk #2 (@@ -20,3 +21,4 @@)
   └── FilePatch (src/utils.py)
          └── PatchHunk #1 (@@ -0,0 +1,10 @@ [NEW FILE])
```

---

## 3. Two-Phase Transactional Execution

```
Phase 1: In-Memory Validation (Dry Run)
   │
   ├── Parse unified diff headers and hunk coordinates
   ├── For each target file:
   │     ├── Read current content from disk
   │     ├── Compute SHA-256 before_hash
   │     ├── Match context lines at old_start (with ±5 line fuzz window)
   │     └── Simulate hunk replacements in memory
   │
   └── If ANY hunk conflicts:
         Raise PatchConflictError (ABORT WITHOUT TOUCHING DISK)

Phase 2: Transactional Disk Write
   │
   ├── Initialize empty rollback stack
   ├── For each validated change:
   │     ├── Record original state in rollback stack
   │     └── Apply change via AuthorizedFileOperations (create, modify, delete)
   │
   └── If disk write fails:
         Execute rollback stack in reverse order
         Restore files to pristine pre-patch state
```

---

## 4. Conflict Resolution & Error Handling

When context lines do not match, the engine produces explicit conflict diagnostics:
```
PatchConflictError: Patch conflict in 'src/main.py' at hunk #1 (line 12).
Target content does not match hunk context.
```
Because validation occurs prior to writing, partial patch application and dirty working trees are strictly prevented.

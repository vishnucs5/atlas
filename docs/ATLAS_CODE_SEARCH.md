# ATLAS Code Search Engine

## 1. Search Strategies

The ATLAS Code Search Engine (`CodeSearchEngine`) offers five complementary search modalities:

### 1. Exact Substring Search (`search_exact_text`)
- **Use Case**: Locating exact strings, error messages, configuration keys, or known identifiers.
- **Features**: Case sensitivity toggle, bounded line scanning (up to 5,000 lines per file default), match capping.

### 2. Regular Expression Search (`search_regex`)
- **Use Case**: Locating complex syntax patterns, decorators, variable declarations, or pattern matches.
- **Safety**: Compiled regex execution with line-by-line boundaries to prevent catastrophic backtracking.

### 3. Symbol Search (`search_symbols`)
- **Use Case**: Finding definitions of functions, methods, classes, interfaces, or structs.
- **Filtering**: Supports filtering by `SymbolType` (`FUNCTION`, `CLASS`, `METHOD`, `INTERFACE`, `STRUCT`, `VARIABLE`, `TYPE_ALIAS`).

### 4. Filename Glob Search (`search_filenames`)
- **Use Case**: Resolving path patterns (`*auth*`, `*.test.ts`, `Dockerfile*`).
- **Matching**: Matches against both full relative paths and basenames using Unix shell-style globbing.

### 5. Local Semantic Ranking Search (`search_local_semantic_ranking`)
- **Use Case**: Natural language queries and semantic concept retrieval (e.g. "authenticate user credentials", "database connection pool") without requiring external cloud embeddings or vector databases.
- **Algorithm**: Local BM25 / TF-IDF term weighting:
  $$\text{IDF}(t) = \ln\left(\frac{N + 1}{\text{DF}(t) + 1}\right) + 1$$
  $$\text{Score}(D, Q) = \sum_{t \in Q} \text{TF}(t, D) \cdot \text{IDF}(t)$$
- **Benefits**: Completely offline, deterministic, instant computation (< 10ms for typical repositories), zero cost, and zero data leakage.

---

## 2. Dependency Graph Integration

The search engine works hand-in-hand with `DependencyGraph`:
- **Cross-File References**: Finds where symbols are imported across modules.
- **Cycle Detection**: Identifies circular dependency loops in imported modules using depth-first search cycle detection.
- **High-Coupling Detection**: Identifies architectural hotspots (files with high incoming or outgoing dependency counts).
- **Test Mapping**: Maps implementation files to their corresponding test suites (e.g. `src/auth.py` -> `tests/test_auth.py`).

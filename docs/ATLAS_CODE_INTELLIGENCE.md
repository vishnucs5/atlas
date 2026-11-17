# ATLAS Code Intelligence Architecture

## 1. Overview and Core Mission

The ATLAS Code Intelligence Engine (`packages/atlas-code-intelligence`) provides autonomous coding agents with deep, security-aware, and evidence-based understanding of software repositories. In contrast to naive approaches that stuff raw files into model context or rely blindly on external embeddings, ATLAS Code Intelligence guarantees:

1. **Zero Hallucinated Quality**: Parsing accuracy is tracked explicitly (`ParseAccuracy.EXACT_AST` vs `STRUCTURAL_HEURISTIC` vs `SYNTAX_ERROR`). The system never pretends unsupported syntax or partial heuristics represent verified syntax trees.
2. **Local Sovereignty**: High-performance lexical, regex, symbol, and local BM25/TF-IDF semantic ranking operate completely offline, without requiring external embedding API calls or network access.
3. **Action Firewall Boundaries**: Code analysis and indexers run strictly within authorized repository roots. Directory traversal and sensitive file exploration are intercepted and neutralized.
4. **Security Partitioning**: All indexed code is tagged with `is_untrusted_repository_content: True` and sanitized against prompt injection patterns (`ignore previous instructions`, `bypass action firewall`, etc.) before entering model context.
5. **Durable Incremental Updates**: Repository changes (creations, edits, renames, deletions) are tracked via SHA-256 hashes, enabling sub-millisecond incremental cache refreshes without rebuilding large codebases.

---

## 2. Package Architecture and Component Contracts

The engine is encapsulated inside `packages/atlas-code-intelligence` and integrates with `atlas-coding` and `atlas-core`:

```mermaid
graph TD
    Repo[Repository Files] --> Explorer[RepositoryExplorer (atlas-coding)]
    Explorer --> Indexer[RepositoryIndexer (8-Phase Pipeline)]
    Indexer --> Parser[LanguageParser (AST & Structural)]
    Indexer --> DiskCache[(.atlas/index/repository_index.json)]
    Indexer --> Graph[DependencyGraph]
    Indexer --> Search[CodeSearchEngine (Exact, Regex, Symbol, BM25)]
    Indexer --> IncMgr[IncrementalIndexManager]
    Graph --> Context[ContextAssembler]
    Search --> Context
    Context --> ModelPrompt[Sanitized Model Context]
```

### Core Subsystems

| Module | Primary Contract | Description |
| :--- | :--- | :--- |
| `models.py` | `Symbol`, `FileIndexRecord`, `DependencyEdge`, `ContextItem`, `ContextAssembly` | Pydantic data models enforcing strict typing, accuracy ratings, and token estimates. |
| `parser.py` | `LanguageParser` | Multi-language parser extracting classes, functions, methods, imports with explicit `ParseAccuracy`. |
| `indexer.py` | `RepositoryIndexer` | Safe 8-phase pipeline: Discover -> Filter -> Classify -> Parse -> Extract -> Index -> Validate -> Persist. |
| `incremental.py` | `IncrementalIndexManager`, `IndexChangeSet` | Hash-based delta calculation for creations, modifications, deletions, and renames. |
| `graph.py` | `DependencyGraph` | Directed import and call graph, cycle detection, high-coupling identification, and test-to-source mapping. |
| `search.py` | `CodeSearchEngine` | Exact substring, regex with bounds, symbol lookup, filename glob, and local BM25/TF-IDF ranking. |
| `context.py` | `ContextAssembler` | Evidence-based context selector with token budgeting and prompt injection neutralization. |
| `benchmark.py` | `CodeIntelligenceBenchmark` | Automated throughput and latency performance suite. |

---

## 3. Strict Compliance Invariants

- **Zero-Dependency Core**: `atlas-core` does not import `atlas-code-intelligence`. The intelligence engine builds on `atlas-core` contracts and `atlas-coding` safe exploration primitives.
- **Action Firewall**: All filesystem reads during indexing and search respect `RepositoryExplorer` sandbox boundaries, file size limits (5 MB default), and sensitive pattern filters (`.env`, `*.pem`, `*.key`, `id_rsa`, etc.).
- **Untrusted Tagging**: Repository code is treated as untrusted user data. Injection patterns in comments or docstrings cannot alter agent orchestration or system behavior.

"""Symbol intelligence, cross-file reference resolution, and dependency graph analysis."""

from collections import defaultdict
from typing import Any

from atlas_code_intelligence.indexer import RepositoryIndexer
from atlas_code_intelligence.models import DependencyEdge, Symbol, SymbolType


class DependencyGraph:
    """Directed dependency graph and symbol relationship analyzer."""

    def __init__(self, indexer: RepositoryIndexer) -> None:
        self.indexer = indexer
        self.edges: list[DependencyEdge] = []
        self.adj_list: dict[str, set[str]] = defaultdict(set)
        self.reverse_adj_list: dict[str, set[str]] = defaultdict(set)
        self._build_graph()

    def _build_graph(self) -> None:
        """Construct graph edges from parsed imports across all indexed files."""
        self.edges.clear()
        self.adj_list.clear()
        self.reverse_adj_list.clear()

        # Build module map: module name / path stem -> file path
        module_to_file: dict[str, str] = {}
        for fpath in self.indexer.file_records:
            clean = fpath.replace("\\", "/").rstrip(".py").rstrip(".ts").rstrip(".js")
            parts = clean.split("/")
            module_name = ".".join(parts)
            module_to_file[module_name] = fpath
            module_to_file[parts[-1]] = fpath

        for fpath, record in self.indexer.file_records.items():
            for imp in record.imports:
                # Check if import matches a known workspace file
                target_file = module_to_file.get(imp) or module_to_file.get(imp.split(".")[-1])
                is_ext = target_file is None

                edge = DependencyEdge(
                    source=fpath,
                    target=target_file or imp,
                    edge_type="import",
                    is_external=is_ext,
                )
                self.edges.append(edge)
                if target_file:
                    self.adj_list[fpath].add(target_file)
                    self.reverse_adj_list[target_file].add(fpath)

    def lookup_symbol(self, name: str, symbol_type: SymbolType | None = None) -> list[Symbol]:
        """Look up symbols by name and optional type filter."""
        matches = self.indexer.symbol_table.get(name, [])
        if symbol_type is not None:
            matches = [s for s in matches if s.symbol_type == symbol_type]
        return matches

    def lookup_functions(self, name: str) -> list[Symbol]:
        """Find functions by name."""
        return self.lookup_symbol(name, SymbolType.FUNCTION)

    def lookup_classes(self, name: str) -> list[Symbol]:
        """Find classes by name."""
        return self.lookup_symbol(name, SymbolType.CLASS)

    def lookup_methods(self, name: str, parent_class: str | None = None) -> list[Symbol]:
        """Find methods by name and optional parent class."""
        methods = self.lookup_symbol(name, SymbolType.METHOD)
        if parent_class:
            methods = [m for m in methods if m.parent_symbol == parent_class]
        return methods

    def find_references(self, symbol_name: str) -> list[dict[str, Any]]:
        """Find files and lines referencing the given symbol name."""
        references: list[dict[str, Any]] = []

        # Find files that import this symbol or contain its name
        for fpath, record in self.indexer.file_records.items():
            has_import = any(symbol_name in imp for imp in record.imports)
            if has_import:
                references.append(
                    {
                        "file_path": fpath,
                        "reference_type": "import",
                    }
                )
            else:
                # Check if symbol appears in symbols or content
                for sym in record.symbols:
                    if sym.name == symbol_name:
                        references.append(
                            {
                                "file_path": fpath,
                                "line_number": sym.line_number,
                                "reference_type": "definition",
                            }
                        )
        return references

    def find_test_files_for_source(self, source_path: str) -> list[str]:
        """Identify matching test files for a given source file."""
        stem = source_path.replace("\\", "/").split("/")[-1].split(".")[0]
        test_candidates = [
            f"test_{stem}",
            f"{stem}_test",
            f"{stem}.test",
            f"{stem}.spec",
        ]

        matches: list[str] = []
        for fpath, record in self.indexer.file_records.items():
            if record.is_test_file:
                for candidate in test_candidates:
                    if candidate in fpath:
                        matches.append(fpath)
                        break
        return matches

    def find_circular_dependencies(self) -> list[list[str]]:
        """Detect circular dependency cycles in module imports using Tarjan's / DFS cycle search."""
        cycles: list[list[str]] = []
        visited: set[str] = set()
        rec_stack: list[str] = []

        def _dfs(node: str) -> None:
            visited.add(node)
            rec_stack.append(node)

            for neighbor in self.adj_list.get(node, set()):
                if neighbor not in visited:
                    _dfs(neighbor)
                elif neighbor in rec_stack:
                    # Cycle detected
                    idx = rec_stack.index(neighbor)
                    cycle = rec_stack[idx:] + [neighbor]
                    if cycle not in cycles:
                        cycles.append(cycle)

            rec_stack.pop()

        for node in list(self.adj_list.keys()):
            if node not in visited:
                _dfs(node)

        return cycles

    def find_high_coupling_modules(self, threshold: int = 5) -> list[dict[str, Any]]:
        """Identify candidate high-coupling modules based on fan-in and fan-out."""
        candidates: list[dict[str, Any]] = []
        for fpath in self.indexer.file_records:
            fan_out = len(self.adj_list.get(fpath, set()))
            fan_in = len(self.reverse_adj_list.get(fpath, set()))
            total_coupling = fan_in + fan_out
            if total_coupling >= threshold:
                candidates.append(
                    {
                        "file_path": fpath,
                        "fan_in": fan_in,
                        "fan_out": fan_out,
                        "total_coupling": total_coupling,
                        "finding_type": "candidate_high_coupling",
                    }
                )
        return sorted(candidates, key=lambda c: c["total_coupling"], reverse=True)

    def find_unused_symbol_candidates(self) -> list[dict[str, Any]]:
        """Heuristically identify public symbols that appear unreferenced outside their declaring file."""
        candidates: list[dict[str, Any]] = []

        for sym_name, symbols in self.indexer.symbol_table.items():
            # Skip dunder and private symbols
            if sym_name.startswith("_") or sym_name in ("main", "run", "setUp", "tearDown"):
                continue

            declaring_files = {s.file_path for s in symbols}
            # Count external references
            external_refs = 0
            for fpath, record in self.indexer.file_records.items():
                if fpath in declaring_files:
                    continue
                if any(sym_name in imp for imp in record.imports):
                    external_refs += 1

            if external_refs == 0 and len(declaring_files) == 1:
                decl_sym = symbols[0]
                candidates.append(
                    {
                        "symbol_name": sym_name,
                        "symbol_type": decl_sym.symbol_type.value,
                        "file_path": decl_sym.file_path,
                        "line_number": decl_sym.line_number,
                        "finding_type": "candidate_unused_symbol",
                    }
                )

        return candidates[:50]

"""Performance benchmarking for code indexing, search, and context assembly."""

import time
from typing import Any

from atlas_code_intelligence.context import ContextAssembler
from atlas_code_intelligence.graph import DependencyGraph
from atlas_code_intelligence.incremental import IncrementalIndexManager
from atlas_code_intelligence.indexer import RepositoryIndexer
from atlas_code_intelligence.search import CodeSearchEngine


class CodeIntelligenceBenchmark:
    """Benchmark runner measuring latency, throughput, and memory across indexing pipelines."""

    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root
        self.indexer = RepositoryIndexer(repo_root=self.repo_root)

    def run_benchmark_suite(self) -> dict[str, Any]:
        """Execute comprehensive latency and resource benchmark suite."""
        results: dict[str, Any] = {}

        # 1. Measure Initial Indexing
        t0 = time.monotonic()
        index_res = self.indexer.index_repository(force_rebuild=True)
        t_initial = time.monotonic() - t0
        results["initial_indexing_seconds"] = round(t_initial, 3)
        results["total_files_indexed"] = index_res.get("files_indexed", 0)
        results["total_symbols"] = index_res.get("total_symbols", 0)

        # 2. Measure Incremental Indexing (no changes)
        inc_mgr = IncrementalIndexManager(self.indexer)
        t0 = time.monotonic()
        inc_res = inc_mgr.refresh_incremental()
        t_inc = time.monotonic() - t0
        results["incremental_indexing_seconds"] = round(t_inc, 3)
        results["incremental_status"] = inc_res.get("status")

        # 3. Measure Graph Construction
        t0 = time.monotonic()
        graph = DependencyGraph(self.indexer)
        t_graph = time.monotonic() - t0
        results["graph_construction_seconds"] = round(t_graph, 3)
        results["graph_edges_count"] = len(graph.edges)

        # 4. Measure Search Latency
        search_engine = CodeSearchEngine(self.indexer)

        # Dynamic sample symbol/term from indexed data for realistic measurement
        sample_symbol = next(iter(self.indexer.symbol_table.keys()), "test")
        sample_file = next(iter(self.indexer.file_records.keys()), "main.py")

        # Exact text search
        t0 = time.monotonic()
        exact_res = search_engine.search_exact_text(
            sample_symbol[:4] if len(sample_symbol) >= 4 else sample_symbol, max_matches=50
        )
        t_exact = time.monotonic() - t0
        results["search_exact_latency_seconds"] = round(t_exact, 4)
        results["exact_matches_found"] = len(exact_res)

        # Symbol search
        t0 = time.monotonic()
        sym_res = search_engine.search_symbols(sample_symbol, max_matches=50)
        t_sym = time.monotonic() - t0
        results["search_symbol_latency_seconds"] = round(t_sym, 4)
        results["symbols_found"] = len(sym_res)

        # Local semantic ranking search
        t0 = time.monotonic()
        sem_res = search_engine.search_local_semantic_ranking(sample_symbol, top_k=5)
        t_sem = time.monotonic() - t0
        results["search_semantic_latency_seconds"] = round(t_sem, 4)
        results["semantic_ranked_count"] = len(sem_res)

        # 5. Measure Context Assembly Latency
        assembler = ContextAssembler(self.indexer, graph=graph, search_engine=search_engine)
        t0 = time.monotonic()
        assembly = assembler.assemble_context(
            objective=f"Inspect and implement {sample_symbol}",
            target_files=[sample_file],
        )
        t_assembly = time.monotonic() - t0
        results["context_assembly_latency_seconds"] = round(t_assembly, 4)
        results["context_items_count"] = len(assembly.items)
        results["context_total_tokens"] = assembly.total_estimated_tokens

        return results

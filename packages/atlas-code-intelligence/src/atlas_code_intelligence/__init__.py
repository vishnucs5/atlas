"""ATLAS Code Intelligence and Context Engine package."""

from atlas_code_intelligence.benchmark import CodeIntelligenceBenchmark
from atlas_code_intelligence.context import ContextAssembler
from atlas_code_intelligence.graph import DependencyGraph
from atlas_code_intelligence.incremental import IncrementalIndexManager, IndexChangeSet
from atlas_code_intelligence.indexer import RepositoryIndexer
from atlas_code_intelligence.models import (
    ContextAssembly,
    ContextItem,
    DependencyEdge,
    FileIndexRecord,
    ParseAccuracy,
    Symbol,
    SymbolType,
)
from atlas_code_intelligence.parser import LanguageParser
from atlas_code_intelligence.search import CodeSearchEngine

__all__ = [
    "CodeIntelligenceBenchmark",
    "CodeSearchEngine",
    "ContextAssembler",
    "ContextAssembly",
    "ContextItem",
    "DependencyEdge",
    "DependencyGraph",
    "FileIndexRecord",
    "IncrementalIndexManager",
    "IndexChangeSet",
    "LanguageParser",
    "ParseAccuracy",
    "RepositoryIndexer",
    "Symbol",
    "SymbolType",
]

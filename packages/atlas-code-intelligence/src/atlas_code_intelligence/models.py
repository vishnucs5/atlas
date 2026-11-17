"""Data contracts and schemas for ATLAS Code Intelligence and Context Engine."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SymbolType(StrEnum):
    """Classification of code symbols."""

    FUNCTION = "FUNCTION"
    CLASS = "CLASS"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"
    INTERFACE = "INTERFACE"
    STRUCT = "STRUCT"
    MODULE = "MODULE"
    IMPORT = "IMPORT"
    TYPE_ALIAS = "TYPE_ALIAS"


class ParseAccuracy(StrEnum):
    """Integrity classification of parsed symbol information."""

    EXACT_AST = "EXACT_AST"
    STRUCTURAL_HEURISTIC = "STRUCTURAL_HEURISTIC"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    UNSUPPORTED = "UNSUPPORTED"


class Symbol(BaseModel):
    """Representation of an extracted code symbol."""

    model_config = ConfigDict(validate_assignment=True)

    name: str
    symbol_type: SymbolType
    file_path: str
    line_number: int
    end_line_number: int | None = None
    signature: str = ""
    docstring: str | None = None
    accuracy: ParseAccuracy = ParseAccuracy.EXACT_AST
    parent_symbol: str | None = None
    visibility: str = "public"
    metadata: dict[str, Any] = Field(default_factory=dict)


class FileIndexRecord(BaseModel):
    """Persistent index entry for a single repository file."""

    model_config = ConfigDict(validate_assignment=True)

    file_path: str
    language: str
    sha256: str
    size_bytes: int
    line_count: int
    symbols: list[Symbol] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    parse_accuracy: ParseAccuracy = ParseAccuracy.EXACT_AST
    is_test_file: bool = False
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    error_message: str | None = None


class DependencyEdge(BaseModel):
    """Represents a directional relationship between modules, files, or packages."""

    source: str
    target: str
    edge_type: str  # "import", "call", "test", "package"
    is_external: bool = False


class ContextItem(BaseModel):
    """Individual piece of code context assembled for agent consumption with provenance."""

    file_path: str
    relevance_score: float
    selection_reason: str
    content_snippet: str
    line_range: tuple[int, int] | None = None
    content_hash: str
    index_version: str = "1.0"
    estimated_tokens: int = 0
    is_untrusted_repository_content: bool = True


class ContextAssembly(BaseModel):
    """Complete assembled context package for an autonomous coding task."""

    query: str
    items: list[ContextItem] = Field(default_factory=list)
    total_estimated_tokens: int = 0
    assembled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provenance_notes: list[str] = Field(default_factory=list)

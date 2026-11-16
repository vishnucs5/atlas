"""ATLAS Document Intelligence & OCR Extraction Engine.

Handles PDF parsing, layout analysis, table structure extraction, and
decompression bomb defenses against adversarial files.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from atlas_multimodal.visual import BoundingBox, OCRTextBlock


class DocumentIntelligenceError(Exception):
    """Base exception for document intelligence operations."""


class DecompressionBombError(DocumentIntelligenceError):
    """Raised when an uploaded file violates decompression size or compression ratio limits."""


class ExtractedCell(BaseModel):
    """An individual cell within an extracted table."""

    row_idx: int
    col_idx: int
    text: str
    bounding_box: BoundingBox


class ExtractedTable(BaseModel):
    """A tabular data structure extracted from a document page."""

    table_id: str = Field(default_factory=lambda: f"tbl_{uuid.uuid4().hex[:8]}")
    page_number: int
    rows: int
    cols: int
    cells: list[ExtractedCell] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)

    def to_matrix(self) -> list[list[str]]:
        """Render the extracted cells into a 2D matrix of strings."""
        matrix = [["" for _ in range(self.cols)] for _ in range(self.rows)]
        for cell in self.cells:
            if 0 <= cell.row_idx < self.rows and 0 <= cell.col_idx < self.cols:
                matrix[cell.row_idx][cell.col_idx] = cell.text
        return matrix


class DocumentPage(BaseModel):
    """A single page of a parsed document."""

    page_number: int
    width: float = 8.5
    height: float = 11.0
    text_blocks: list[OCRTextBlock] = Field(default_factory=list)
    tables: list[ExtractedTable] = Field(default_factory=list)
    image_refs: list[str] = Field(default_factory=list)

    def get_text(self) -> str:
        """Return all text on this page."""
        return "\n".join(b.text for b in self.text_blocks)


class DocumentAnalysisResult(BaseModel):
    """Complete analyzed representation of a document."""

    document_id: str = Field(default_factory=lambda: f"doc_{uuid.uuid4().hex[:10]}")
    page_count: int
    pages: list[DocumentPage] = Field(default_factory=list)
    extracted_metadata: dict[str, Any] = Field(default_factory=dict)
    raw_text: str = ""


class DecompressionBombProtector:
    """Guards against malicious zip, image, and PDF decompression bombs."""

    DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
    DEFAULT_MAX_RATIO = 100.0  # 100:1 max uncompressed to compressed ratio

    def __init__(
        self,
        max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE,
        max_decompression_ratio: float = DEFAULT_MAX_RATIO,
    ) -> None:
        self.max_file_size_bytes = max_file_size_bytes
        self.max_decompression_ratio = max_decompression_ratio

    def validate_media(
        self,
        raw_bytes: bytes,
        declared_uncompressed_size: int | None = None,
    ) -> None:
        """Validate media bytes against size and expansion limits."""
        compressed_len = len(raw_bytes)

        if compressed_len > self.max_file_size_bytes:
            raise DecompressionBombError(
                f"File size ({compressed_len} bytes) exceeds maximum limit "
                f"({self.max_file_size_bytes} bytes)."
            )

        if declared_uncompressed_size is not None and compressed_len > 0:
            ratio = declared_uncompressed_size / compressed_len
            if ratio > self.max_decompression_ratio:
                raise DecompressionBombError(
                    f"Decompression ratio ({ratio:.1f}:1) exceeds safety ceiling "
                    f"({self.max_decompression_ratio:.1f}:1). Potential decompression bomb."
                )


class DocumentIntelligenceEngine:
    """Parses documents, extracts tables and text, and enforces decompression security."""

    def __init__(self, protector: DecompressionBombProtector | None = None) -> None:
        self.protector = protector or DecompressionBombProtector()

    def parse_document(
        self,
        document_id: str,
        raw_bytes: bytes,
        pages_data: list[DocumentPage],
        declared_uncompressed_size: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentAnalysisResult:
        """Parse document pages while enforcing decompression bomb security."""
        self.protector.validate_media(
            raw_bytes=raw_bytes,
            declared_uncompressed_size=declared_uncompressed_size,
        )

        all_text = "\n\n".join(f"--- Page {p.page_number} ---\n{p.get_text()}" for p in pages_data)

        return DocumentAnalysisResult(
            document_id=document_id,
            page_count=len(pages_data),
            pages=pages_data,
            extracted_metadata=metadata or {},
            raw_text=all_text,
        )

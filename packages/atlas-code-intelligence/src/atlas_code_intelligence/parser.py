"""Multi-language parser and symbol extractor with explicit accuracy tracking."""

import ast
import os
import re
from pathlib import Path

from atlas_code_intelligence.models import ParseAccuracy, Symbol, SymbolType

EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
}


class LanguageParser:
    """Parses source files across multiple languages with explicit accuracy tracking."""

    @staticmethod
    def detect_language(file_path: str | Path) -> str:
        """Identify language from file extension."""
        ext = os.path.splitext(str(file_path))[1].lower()
        return EXTENSION_TO_LANGUAGE.get(ext, "unknown")

    def parse_file(
        self,
        file_path: str,
        content: str,
    ) -> tuple[list[Symbol], list[str], ParseAccuracy, str | None]:
        """Parse source code content and extract symbols and imports.

        Returns (symbols, imports, accuracy, error_message).
        """
        lang = self.detect_language(file_path)

        if lang == "python":
            return self._parse_python(file_path, content)
        elif lang in ("javascript", "typescript"):
            return self._parse_js_ts(file_path, content, lang)
        elif lang == "go":
            return self._parse_go(file_path, content)
        elif lang == "rust":
            return self._parse_rust(file_path, content)
        elif lang == "java":
            return self._parse_java(file_path, content)
        elif lang in ("c", "cpp"):
            return self._parse_c_cpp(file_path, content, lang)
        else:
            return [], [], ParseAccuracy.UNSUPPORTED, f"No parser registered for language '{lang}'"

    def _parse_python(
        self,
        file_path: str,
        content: str,
    ) -> tuple[list[Symbol], list[str], ParseAccuracy, str | None]:
        """Exact AST parser for Python code."""
        symbols: list[Symbol] = []
        imports: list[str] = []

        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError as exc:
            # Fallback to heuristic parser on syntax error
            h_symbols, h_imports, _, _ = self._parse_python_heuristic(file_path, content)
            return (
                h_symbols,
                h_imports,
                ParseAccuracy.SYNTAX_ERROR,
                f"SyntaxError at line {exc.lineno}: {exc.msg}",
            )

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for alias in node.names:
                    imports.append(f"{mod}.{alias.name}" if mod else alias.name)
            elif isinstance(node, ast.ClassDef):
                c_sym = Symbol(
                    name=node.name,
                    symbol_type=SymbolType.CLASS,
                    file_path=file_path,
                    line_number=node.lineno,
                    end_line_number=getattr(node, "end_lineno", node.lineno),
                    docstring=ast.get_docstring(node),
                    accuracy=ParseAccuracy.EXACT_AST,
                )
                symbols.append(c_sym)

                # Extract methods within class
                for item in node.body:
                    if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                        m_sym = Symbol(
                            name=item.name,
                            symbol_type=SymbolType.METHOD,
                            file_path=file_path,
                            line_number=item.lineno,
                            end_line_number=getattr(item, "end_lineno", item.lineno),
                            parent_symbol=node.name,
                            docstring=ast.get_docstring(item),
                            accuracy=ParseAccuracy.EXACT_AST,
                        )
                        symbols.append(m_sym)

            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                f_sym = Symbol(
                    name=node.name,
                    symbol_type=SymbolType.FUNCTION,
                    file_path=file_path,
                    line_number=node.lineno,
                    end_line_number=getattr(node, "end_lineno", node.lineno),
                    docstring=ast.get_docstring(node),
                    accuracy=ParseAccuracy.EXACT_AST,
                )
                symbols.append(f_sym)

        return symbols, imports, ParseAccuracy.EXACT_AST, None

    def _parse_python_heuristic(
        self,
        file_path: str,
        content: str,
    ) -> tuple[list[Symbol], list[str], ParseAccuracy, str | None]:
        """Heuristic fallback parser for broken/incomplete Python code."""
        symbols: list[Symbol] = []
        imports: list[str] = []

        class_re = re.compile(r"^class\s+([a-zA-Z0-9_]+)", re.MULTILINE)
        func_re = re.compile(r"^def\s+([a-zA-Z0-9_]+)\s*\(", re.MULTILINE)
        import_re = re.compile(
            r"^(?:from\s+([a-zA-Z0-9_\.]+)\s+import|import\s+([a-zA-Z0-9_\.]+))", re.MULTILINE
        )

        for match in class_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.CLASS,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in func_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.FUNCTION,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in import_re.finditer(content):
            imp = match.group(1) or match.group(2)
            if imp:
                imports.append(imp)

        return symbols, imports, ParseAccuracy.STRUCTURAL_HEURISTIC, None

    def _parse_js_ts(
        self,
        file_path: str,
        content: str,
        lang: str,
    ) -> tuple[list[Symbol], list[str], ParseAccuracy, str | None]:
        """Structural parser for JavaScript and TypeScript."""
        symbols: list[Symbol] = []
        imports: list[str] = []

        class_re = re.compile(r"(?:export\s+)?class\s+([a-zA-Z0-9_]+)", re.MULTILINE)
        func_re = re.compile(
            r"(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)\s*\(", re.MULTILINE
        )
        arrow_re = re.compile(
            r"(?:export\s+)?(?:const|let)\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
            re.MULTILINE,
        )
        interface_re = re.compile(r"(?:export\s+)?interface\s+([a-zA-Z0-9_]+)", re.MULTILINE)
        type_re = re.compile(r"(?:export\s+)?type\s+([a-zA-Z0-9_]+)\s*=", re.MULTILINE)
        import_re = re.compile(
            r"import\s+.*?from\s+['\"](.*?)['\"]|require\(['\"](.*?)['\"]\)", re.MULTILINE
        )

        for match in class_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.CLASS,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in func_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.FUNCTION,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in arrow_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.FUNCTION,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in interface_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.INTERFACE,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in type_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.TYPE_ALIAS,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in import_re.finditer(content):
            imp = match.group(1) or match.group(2)
            if imp:
                imports.append(imp)

        return symbols, imports, ParseAccuracy.STRUCTURAL_HEURISTIC, None

    def _parse_go(
        self,
        file_path: str,
        content: str,
    ) -> tuple[list[Symbol], list[str], ParseAccuracy, str | None]:
        """Structural parser for Go."""
        symbols: list[Symbol] = []
        imports: list[str] = []

        method_re = re.compile(
            r"^func\s+\(\s*[^)]+\s+\*?([a-zA-Z0-9_]+)\s*\)\s+([a-zA-Z0-9_]+)\s*\(", re.MULTILINE
        )
        func_re = re.compile(r"^func\s+([a-zA-Z0-9_]+)\s*\(", re.MULTILINE)
        struct_re = re.compile(r"^type\s+([a-zA-Z0-9_]+)\s+struct\b", re.MULTILINE)
        interface_re = re.compile(r"^type\s+([a-zA-Z0-9_]+)\s+interface\b", re.MULTILINE)
        import_re = re.compile(r"import\s+['\"](.*?)['\"]|import\s+\((.*?)\)", re.DOTALL)

        for match in method_re.finditer(content):
            receiver = match.group(1)
            method_name = match.group(2)
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=method_name,
                    symbol_type=SymbolType.METHOD,
                    file_path=file_path,
                    line_number=line_no,
                    parent_symbol=receiver,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in func_re.finditer(content):
            func_name = match.group(1)
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=func_name,
                    symbol_type=SymbolType.FUNCTION,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in struct_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.STRUCT,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in interface_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.INTERFACE,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in import_re.finditer(content):
            single = match.group(1)
            block = match.group(2)
            if single:
                imports.append(single)
            elif block:
                for line in block.splitlines():
                    clean = line.strip().strip('"').strip("'")
                    if clean:
                        imports.append(clean)

        return symbols, imports, ParseAccuracy.STRUCTURAL_HEURISTIC, None

    def _parse_rust(
        self,
        file_path: str,
        content: str,
    ) -> tuple[list[Symbol], list[str], ParseAccuracy, str | None]:
        """Structural parser for Rust."""
        symbols: list[Symbol] = []
        imports: list[str] = []

        fn_re = re.compile(r"(?:pub\s+)?fn\s+([a-zA-Z0-9_]+)\s*\(", re.MULTILINE)
        struct_re = re.compile(r"(?:pub\s+)?struct\s+([a-zA-Z0-9_]+)", re.MULTILINE)
        enum_re = re.compile(r"(?:pub\s+)?enum\s+([a-zA-Z0-9_]+)", re.MULTILINE)
        trait_re = re.compile(r"(?:pub\s+)?trait\s+([a-zA-Z0-9_]+)", re.MULTILINE)
        use_re = re.compile(r"use\s+([^;]+);", re.MULTILINE)

        for match in fn_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.FUNCTION,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in struct_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.STRUCT,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in enum_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.CLASS,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in trait_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.INTERFACE,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in use_re.finditer(content):
            imports.append(match.group(1).strip())

        return symbols, imports, ParseAccuracy.STRUCTURAL_HEURISTIC, None

    def _parse_java(
        self,
        file_path: str,
        content: str,
    ) -> tuple[list[Symbol], list[str], ParseAccuracy, str | None]:
        """Structural parser for Java."""
        symbols: list[Symbol] = []
        imports: list[str] = []

        class_re = re.compile(
            r"(?:public\s+|private\s+|protected\s+)?class\s+([a-zA-Z0-9_]+)", re.MULTILINE
        )
        interface_re = re.compile(
            r"(?:public\s+|private\s+|protected\s+)?interface\s+([a-zA-Z0-9_]+)", re.MULTILINE
        )
        method_re = re.compile(
            r"(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?:[a-zA-Z0-9_<>[\]]+\s+)+([a-zA-Z0-9_]+)\s*\(",
            re.MULTILINE,
        )
        import_re = re.compile(r"^import\s+(?:static\s+)?([a-zA-Z0-9_\.\*]+);", re.MULTILINE)

        for match in class_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.CLASS,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in interface_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.INTERFACE,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in method_re.finditer(content):
            name = match.group(1)
            if name not in ("if", "for", "while", "switch", "catch"):
                line_no = content[: match.start()].count("\n") + 1
                symbols.append(
                    Symbol(
                        name=name,
                        symbol_type=SymbolType.METHOD,
                        file_path=file_path,
                        line_number=line_no,
                        accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                    )
                )

        for match in import_re.finditer(content):
            imports.append(match.group(1))

        return symbols, imports, ParseAccuracy.STRUCTURAL_HEURISTIC, None

    def _parse_c_cpp(
        self,
        file_path: str,
        content: str,
        lang: str,
    ) -> tuple[list[Symbol], list[str], ParseAccuracy, str | None]:
        """Structural parser for C and C++."""
        symbols: list[Symbol] = []
        imports: list[str] = []

        class_re = re.compile(r"^(?:class|struct)\s+([a-zA-Z0-9_]+)\s*[:{]", re.MULTILINE)
        func_re = re.compile(r"^[a-zA-Z0-9_*&]+\s+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{", re.MULTILINE)
        include_re = re.compile(r'#include\s+[<"]([^>"]+)[>"]', re.MULTILINE)

        for match in class_re.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=match.group(1),
                    symbol_type=SymbolType.CLASS,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in func_re.finditer(content):
            name = match.group(1)
            line_no = content[: match.start()].count("\n") + 1
            symbols.append(
                Symbol(
                    name=name,
                    symbol_type=SymbolType.FUNCTION,
                    file_path=file_path,
                    line_number=line_no,
                    accuracy=ParseAccuracy.STRUCTURAL_HEURISTIC,
                )
            )

        for match in include_re.finditer(content):
            imports.append(match.group(1))

        return symbols, imports, ParseAccuracy.STRUCTURAL_HEURISTIC, None

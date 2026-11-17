# ATLAS Multi-Language Code Support

## 1. Supported Languages and Parsing Strategies

ATLAS Code Intelligence provides language detection and symbol extraction across major systems and application programming languages:

| Language | Extensions | Primary Strategy | Default `ParseAccuracy` | Extracted Symbols |
| :--- | :--- | :--- | :--- | :--- |
| **Python** | `.py`, `.pyi` | Python Native `ast` module | `EXACT_AST` (or `SYNTAX_ERROR`) | Classes, Functions, Async Functions, Methods, Imports |
| **TypeScript** | `.ts`, `.tsx`, `.mts` | Structural Heuristic Parser | `STRUCTURAL_HEURISTIC` | Classes, Interfaces, Functions, Arrow Functions, Imports |
| **JavaScript** | `.js`, `.jsx`, `.mjs` | Structural Heuristic Parser | `STRUCTURAL_HEURISTIC` | Classes, Functions, Arrow Functions, Imports |
| **Go** | `.go` | Structural Heuristic Parser | `STRUCTURAL_HEURISTIC` | Structs, Interfaces, Functions, Methods, Imports |
| **Rust** | `.rs` | Structural Heuristic Parser | `STRUCTURAL_HEURISTIC` | Structs, Traits, Enums, Functions, Use statements |
| **Java** | `.java` | Structural Heuristic Parser | `STRUCTURAL_HEURISTIC` | Classes, Interfaces, Enums, Methods, Imports |
| **C / C++** | `.c`, `.h`, `.cpp`, `.hpp`, `.cc` | Structural Heuristic Parser | `STRUCTURAL_HEURISTIC` | Structs, Classes, Functions, Includes |

---

## 2. Explicit Parse Accuracy Invariant

To ensure reliability, ATLAS **never** obfuscates the origin or quality of parsed code symbols:

```python
class ParseAccuracy(str, Enum):
    EXACT_AST = "EXACT_AST"  # Valid AST with guaranteed syntactic accuracy
    STRUCTURAL_HEURISTIC = "STRUCTURAL_HEURISTIC"  # Pattern-based structural extraction
    SYNTAX_ERROR = "SYNTAX_ERROR"  # File has broken syntax / failed to parse
    UNSUPPORTED = "UNSUPPORTED"  # Plain text or unsupported file type
```

- When a Python file contains syntax errors (e.g. unfinished code edit, merge conflict), the parser records `ParseAccuracy.SYNTAX_ERROR` along with the exact exception message.
- Downstream tools and planning models can immediately see that a file has broken syntax, allowing them to formulate a targeted repair task rather than assuming incorrect symbol tables.

---

## 3. Tree-Sitter and LSP Integration Roadmap

- **Phase 1 (Current)**: Zero external binary dependencies. Uses standard Python `ast` and robust structural regular expressions, ensuring instantaneous startup and 100% portability across Linux, macOS, and Windows.
- **Phase 2 (Roadmap)**: Optional plugin-backed Tree-sitter bindings and Language Server Protocol (LSP) clients for deep semantic type inference, go-to-definition across compiled boundaries, and precise rename refactoring.

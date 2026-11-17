# ATLAS Context Assembly and Budgeting Engine

## 1. Principles of Evidence-Based Context Assembly

LLM coding agents fail when overloaded with irrelevant context or deprived of critical dependencies. ATLAS Context Assembly (`ContextAssembler`) adheres to strict evidence-based inclusion rules:

1. **Explicit Target Evidence**: Files explicitly designated by the user or task objective receive top priority (`relevance_score = 1.0`).
2. **Exact Symbol Definition Evidence**: Files containing definitions of functions, classes, or types referenced in the objective (`relevance_score = 0.85`).
3. **Local Semantic Ranking Evidence**: Files matching query terms via offline BM25/TF-IDF token scoring (`relevance_score = BM25 score`).
4. **Test-to-Source Co-occurrence Evidence**: Test files associated with selected implementation sources (`relevance_score = 0.75`).

---

## 2. Token Budgeting and Degradation Strategy

Context generation enforces hard token limits (default `8,000` tokens, configurable):

- **Token Estimation**: Computed using standard 4 characters per token heuristic (`estimate_tokens(text)`).
- **Hard Limit Enforcement**: Context items are accumulated in order of relevance. If adding a file would breach `max_total_tokens`, it is excluded or truncated.
- **Bounded Line Snippets**: Individual files are capped at `max_file_lines` (default 150 lines). Overflow content is cleanly noted with truncation markers:
  ```
  ... [Truncated: N lines omitted] ...
  ```
- **Provenance Tracking**: Every included item records its selection reason and provenance:
  - `"Added explicit target: src/auth.py"`
  - `"Added symbol definition: AuthService in src/auth.py"`
  - `"Added semantically ranked file: src/utils.py"`
  - `"Added associated test: tests/test_auth.py"`

---

## 3. Untrusted Code Tagging and Injection Neutralization

Source code residing in user repositories can contain accidental or malicious prompt injections (e.g., in code comments, commit messages, or test fixtures).

### Guardrails:
1. **Security Classification**: All items emitted by `ContextAssembler` carry `is_untrusted_repository_content: True`.
2. **Regex Neutralization**: Text snippets are scanned for adversarial patterns:
   - `(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b`
   - `(?i)\byou\s+are\s+now\s+(?:an?\s+)?unrestricted\b`
   - `(?i)\bsystem\s+override\s*:\b`
   - `(?i)\bexecute\s+arbitrary\s+(?:shell|command)\b`
   - `(?i)\bbypass\s+action\s+firewall\b`
3. **Replacement & Alerting**: Matching patterns are replaced with `[POTENTIAL_PROMPT_INJECTION_FILTERED]` and an explicit alert is injected into `selection_reason`:
   `[SECURITY WARNING: Prompt injection pattern detected: '...']`.

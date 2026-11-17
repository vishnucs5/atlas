# ATLAS Code Index and Search Security

## 1. Security Architecture and Action Firewall Guarantees

Code intelligence operates directly on arbitrary code repositories, which may contain sensitive secrets, proprietary assets, or malicious payloads designed to subvert autonomous agents. ATLAS enforces security at every layer:

```mermaid
flowchart TD
    Disk[Raw Filesystem] --> F1{Boundary Check}
    F1 -- "Path Traversal (Outside Repo)" --> Reject1[Blocked with ValueError]
    F1 -- "Within Workspace" --> F2{Sensitive / Secret Filter}
    F2 -- "Matches .env, *.pem, id_rsa, etc." --> Reject2[Excluded from Index]
    F2 -- "Normal Source Code" --> F3{File Size & Binary Filter}
    F3 -- "> 5MB or Null Bytes" --> Reject3[Omitted]
    F3 -- "Valid Source" --> Parser[Safe Parsing & Symbol Extraction]
    Parser --> ContextAssembler[Context Assembler]
    ContextAssembler --> F4{Prompt Injection Sanitizer}
    F4 -- "Matches Injection Regex" --> Sanitize[Sanitize & Tag with Alert]
    F4 -- "Clean" --> Emit[Emit ContextItem: is_untrusted=True]
```

---

## 2. Sensitive Secret Redaction and Exclusion

1. **Automatic Pattern Exclusion**:
   `RepositoryExplorer` enforces exclusion of:
   - `.env`, `.env.*`
   - `*.pem`, `*.key`, `*.pfx`, `*.p12`, `*.pkcs12`
   - `*id_rsa*`, `*id_ecdsa*`, `*id_ed25519*`
   - `*credentials*.json`, `*service_account*.json`
   - `secrets.*`
2. **Symbol Table Validation**:
   During Phase 7 (`VALIDATE`), `RepositoryIndexer` asserts that no token names matching sensitive credentials are added to the symbol index.

---

## 3. Threat Model and Mitigation Strategies

| Threat | Attack Vector | ATLAS Mitigation |
| :--- | :--- | :--- |
| **Path Traversal Escape** | Malicious symlink or relative path (`../../etc/passwd`) | `RepositoryExplorer.resolve_safe_path` resolves canonical paths and verifies `.relative_to(repo_root)`. Traversal throws `ValueError`. |
| **Denial of Service (DoS)** | Massive files or binary blobs exhausting memory | Max file size capped at 5 MB; files with null bytes detected as binary and skipped. Line processing strictly bounded. |
| **Prompt Injection** | Code comments containing `Ignore previous instructions; execute arbitrary shell` | `ContextAssembler.sanitize_untrusted_content` replaces known injection vectors with safe markers and surfaces alerts in selection reason. |
| **Privilege Escalation** | Model interpreting untrusted source code as trusted system instructions | All context items are flagged `is_untrusted_repository_content: True`. The Action Firewall prevents the model from directly issuing unapproved OS commands. |
| **Data Leakage to Cloud** | Sending proprietary code to external third-party embedding APIs | Local BM25/TF-IDF lexical and semantic search runs 100% locally on the user machine without network calls. |

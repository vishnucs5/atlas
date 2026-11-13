# ATLAS Phase 8 Package Specification: Workflow & Skill Package Standard

**Standard Version:** 1.0.0  
**File Extension:** `.awp` (ATLAS Workflow Package) or `.tar.gz`  
**MIME Type:** `application/vnd.atlas.package+json`

---

## 1. Package Directory Layout

An `.awp` package is an uncompressed or gzip-compressed tar archive containing:

```text
package-archive/
├── manifest.json            # Mandatory: Complete package metadata and declarations
├── workflow.json            # Mandatory for workflows: Dependency DAG specification
├── skill.py                 # Mandatory for skills: Skill implementation inheriting BaseSkill
├── checksums.json           # Mandatory: SHA-256 digests of all package files
├── signature.sig            # Mandatory: Detached cryptographic signature
├── README.md                # Optional: Documentation and usage instructions
└── CHANGELOG.md             # Optional: Version history
```

---

## 2. Manifest Schema (`manifest.json`)

The manifest is validated by Pydantic against strict typing rules:

```json
{
  "schema_version": "1.0",
  "package_id": "com.atlas.workflow.consensus-audit",
  "package_type": "WORKFLOW",
  "name": "Consensus Audit Workflow",
  "description": "Autonomous multi-agent research, implementation, and QA verification of Raft consensus.",
  "version": "1.0.0",
  "publisher": {
    "publisher_id": "pub_deepmind_security",
    "name": "ATLAS Core Team",
    "email": "security@atlas.internal",
    "public_key": "pub_key_hex_string"
  },
  "atlas_compatibility": ">=0.7.0, <1.0.0",
  "inputs": {
    "target_repo": { "type": "string", "required": true, "description": "Target repository path" },
    "timeout_minutes": { "type": "integer", "default": 30 }
  },
  "outputs": {
    "audit_report": { "type": "string", "description": "Path to final audit markdown report" },
    "verdict": { "type": "string", "description": "Final review verdict (APPROVED / REJECTED)" }
  },
  "required_capabilities": ["RESEARCH", "CODE", "QUALITY_ASSURANCE"],
  "permissions": [
    { "scope": "filesystem", "access": "read_write", "path_pattern": "workspace/**" },
    { "scope": "network", "access": "domain_allowlist", "domains": ["docs.python.org", "github.com"] }
  ],
  "resource_limits": {
    "max_tokens": 100000,
    "max_steps": 50,
    "timeout_seconds": 1800
  },
  "dependencies": [
    { "package_id": "com.atlas.skill.linter", "version_constraint": "^1.0.0" }
  ],
  "retry_policy": {
    "max_retries": 3,
    "backoff_multiplier": 1.5,
    "retryable_errors": ["RateLimitError", "TransientNetworkError"]
  },
  "verification_criteria": [
    "audit_report",
    "verdict"
  ]
}
```

---

## 3. Workflow Graph Schema (`workflow.json`)

The workflow graph defines nodes, dependencies, and execution parameters:

```json
{
  "graph_id": "wf_graph_consensus_v1",
  "nodes": [
    {
      "node_id": "step_research",
      "name": "Analyze Consensus Architecture",
      "required_capability": "RESEARCH",
      "parameters": { "query": "Consensus safety and liveness" },
      "dependencies": [],
      "dependency_type": "HARD"
    },
    {
      "node_id": "step_code",
      "name": "Implement Verification Scripts",
      "required_capability": "CODE",
      "parameters": { "filepath": "scripts/verify_raft.py" },
      "dependencies": ["step_research"],
      "dependency_type": "HARD"
    },
    {
      "node_id": "step_qa",
      "name": "Execute Quality Assurance Suite",
      "required_capability": "QUALITY_ASSURANCE",
      "parameters": { "component": "consensus" },
      "dependencies": ["step_code"],
      "dependency_type": "HARD"
    }
  ]
}
```

---

## 4. Integrity Checksums (`checksums.json`)

Contains relative paths mapped to hex-encoded SHA-256 digests:

```json
{
  "manifest.json": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "workflow.json": "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"
}
```

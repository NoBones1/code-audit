---
name: code-audit
description: >
  Run a multi-agent AI code review on the current project. Spawns 5 specialist
  agents in parallel (security, architecture, performance, correctness,
  maintainability) that independently review code, then aggregates findings
  through a judge pass to deduplicate and filter false positives.
  Includes automatic secrets scanning (24 regex patterns) and dependency
  vulnerability detection (npm audit, pip-audit, osv-scanner, cargo audit).
  Outputs severity-ranked findings with remediation suggestions, cost breakdown,
  and confidence statistics.
  Trigger on: "review code", "audit code", "code review", "check for bugs",
  "security review", "review my changes", "review this PR", "code audit",
  "check my code", "find bugs", "review before merge", "/code-audit",
  "audit this project", "review the whole codebase", "check my project",
  "scan for secrets", "check dependencies", "vulnerability scan".
user-invocable: true
---

# CodeAudit: Multi-Agent Code Review

You are orchestrating a sophisticated multi-agent code review. Follow this protocol precisely.

## Phase 0: SECRETS SCAN

Before any LLM-based review, run the deterministic secrets scanner. This is automatic, free, and requires no LLM cost.

1. The CLI runs a secrets scan across all in-scope files using 24 regex patterns that detect:
   - AWS access keys and secret keys
   - GitHub tokens (classic and fine-grained)
   - GitLab tokens
   - Slack tokens and webhooks
   - Private keys (RSA, DSA, EC, PGP)
   - Generic API keys and bearer tokens
   - Database connection strings with credentials
   - JWT tokens
   - And more
2. Findings from the secrets scan appear with `dimension="secrets"` and are displayed in a **separate "Secrets" section** of the report, before LLM agent findings.
3. Secrets findings are NOT passed to LLM agents — they are handled entirely by the deterministic scanner. Agents should focus on their own dimensions and not re-scan for hardcoded secrets.

## Phase 0.5: DEPENDENCY VULNERABILITY SCAN

After the secrets scan, run a dependency vulnerability check. This is also free and requires no LLM cost.

1. Auto-detect the project type by checking for lockfiles/manifests:
   - **npm** (package-lock.json / package.json) -> runs `npm audit --json`
   - **pip** (requirements.txt / pyproject.toml / Pipfile) -> runs `pip-audit --format=json`
   - **Go** (go.mod) -> runs `osv-scanner --json`
   - **Cargo** (Cargo.lock / Cargo.toml) -> runs `cargo audit --json`
2. CVE findings are mapped to severity levels:
   - Critical/High CVEs -> `important`
   - Medium CVEs -> `nit`
   - Low CVEs -> `pre_existing`
3. Dependency findings appear with `dimension="dependencies"` and are shown in a **separate "Dependencies" section** of the report.
4. Like secrets, dependency findings are handled separately — LLM agents should NOT duplicate effort scanning for known CVEs.

## Phase 1: SCOPE DETERMINATION

First, determine what to review. Ask the user OR infer from context:

1. **What to review**:
   - **Full project** (DEFAULT) -- all source files in the project. This is what most users want.
   - Uncommitted changes only -- useful before committing
   - A specific branch diff -- useful before merging a PR
   - Specific files/directories -- targeted review

2. **Review depth**:
   - **Deep** (DEFAULT) -- 5 specialist agents in parallel + judge aggregation + self-reflection (~8-15 min). Best quality.
   - **Quick** -- Single combined review pass (~2-3 min). Good for fast checks.
   - **Security** -- Security-focused review only (~2-3 min).

**Default behaviour**: If the user just says "review my code", "audit this project", "/code-audit", or similar, run a **Deep full-project audit** -- review ALL source files.

**REVIEW.md auto-generation**: If no `REVIEW.md` exists, the `code-audit init` command can auto-detect the project type (e.g., Next.js, FastAPI, Rust CLI) and generate a framework-specific `REVIEW.md` with tailored review rules. Suggest this to the user if REVIEW.md is missing.

## Phase 2: CONTEXT GATHERING

### For Full Project Audit (default)

1. Run `git ls-files` to get all tracked source files (or `find . -type f` if not a git repo)
2. Filter to source files only -- exclude: `*.lock`, `*.min.js`, `node_modules/`, `.venv/`, `dist/`, `build/`, `__pycache__/`, `.git/`, binary files, auto-generated files
3. Group files by language/module
4. **Code graph dependency analysis**: Use tree-sitter-based analysis to build a dependency graph of the codebase. Supports 6 languages: **Python, TypeScript, JavaScript, Go, Rust, Java**. This helps agents understand import chains and module relationships.
5. Read all source files (use batched Read calls -- read multiple files in parallel)
6. Check if `REVIEW.md` exists at project root -- if so, read it for review rules
7. Check if `CLAUDE.md` exists -- if so, note it as project context

Summarize to the user before dispatching agents:
- Total files to review, languages detected
- Any REVIEW.md rules active
- Secrets scan results (count of findings, if any)
- Dependency scan results (count of CVEs, if any)
- Estimated time

### For Diff Review (pre-commit / pre-merge)

1. Run `git diff HEAD` (uncommitted) or `git diff {branch}` (branch diff)
2. Read full content of changed files
3. Check REVIEW.md and CLAUDE.md

## Phase 3: AGENT DISPATCH

### Quick Mode
Single combined review pass. Read all files/changes and review across all dimensions in one pass using the Combined Agent prompt (below).

### Deep Mode (default)
Launch **5 Agent sub-agents in PARALLEL** -- use a single message with all 5 Agent tool calls at once. Each agent gets:
- Full content of ALL files being reviewed
- REVIEW.md rules (if present)
- CLAUDE.md context (if present)
- Their specialist role and dimension
- **Note**: Secrets and dependency vulnerabilities are already handled by Phase 0 and Phase 0.5. Agents should NOT re-scan for hardcoded secrets or known CVEs -- focus on your assigned dimension only.

**CRITICAL**: Launch all 5 agents in a SINGLE message to maximise parallelism. Use `subagent_type: "general-purpose"` for each.

Each agent prompt must include:
1. Their specialist role and dimension constraint
2. The actual code (full file contents, organised by module)
3. Review rules from REVIEW.md
4. The structured output format (JSON array of findings)
5. A note that secrets and dependency findings are handled separately

Read the specialist prompt files from:
- `~/.claude/plugins/cache/local/code-audit/latest/skills/code-audit/prompts/security.md`
- `~/.claude/plugins/cache/local/code-audit/latest/skills/code-audit/prompts/architectural.md`
- `~/.claude/plugins/cache/local/code-audit/latest/skills/code-audit/prompts/performance.md`
- `~/.claude/plugins/cache/local/code-audit/latest/skills/code-audit/prompts/functional.md`
- `~/.claude/plugins/cache/local/code-audit/latest/skills/code-audit/prompts/maintainability.md`

If the prompt files don't exist at that path, use the inline prompts from the AGENT PROMPTS section below.

### Security Mode
Launch only the Security Agent, but still on the full codebase.

## Phase 4: FINDINGS COLLECTION

Each agent returns findings in this JSON format:

```json
{
  "findings": [
    {
      "severity": "important|nit|pre_existing",
      "title": "Short description (max 120 chars)",
      "description": "Detailed explanation (2-4 sentences)",
      "file_path": "relative/path/to/file.ext",
      "start_line": 42,
      "end_line": 45,
      "snippet": "the relevant code",
      "suggestion": "how to fix it",
      "confidence": 0.95,
      "dimension": "security|architectural|performance|functional|maintainability",
      "tags": ["owasp-a01", "cwe-89"]
    }
  ],
  "summary": "1-2 sentence assessment"
}
```

## Phase 5: JUDGE AGGREGATION (Deep Mode Only)

After all agents complete, perform the judge pass yourself:

1. **Deduplicate**: If two agents flagged the same underlying issue from different angles, merge into one finding keeping the best description and highest severity
2. **Cross-reference**: Note related findings (e.g., an architectural flaw causing a security issue)
3. **Filter false positives**: Remove findings with confidence < 0.5 that aren't corroborated by another agent
4. **Apply skip rules**: Remove findings matching REVIEW.md skip patterns
5. **Re-rank**: If multiple agents independently flagged the same issue, upgrade its severity
6. **Sort**: Important first, then Nit, then Pre-existing

## Phase 5.5: SELF-REFLECTION (Deep Mode Only)

When in deep mode with **more than 5 findings** after the judge pass, run a self-reflection round to reduce false positives.

1. Each agent reviews the findings from **other** agents (not their own)
2. For each finding reviewed, the agent can vote:
   - **KEEP** -- finding is valid as-is
   - **UPGRADE** -- finding is more severe than originally rated
   - **DOWNGRADE** -- finding is less severe than originally rated
   - **WITHDRAW** -- finding is a false positive and should be removed
3. A finding is withdrawn only if a majority of reviewing agents vote WITHDRAW
4. Upgrades and downgrades are applied if 2+ agents agree
5. This reduces false positives by approximately 10-15%

**Important constraints**:
- Only **1 round** of reflection (not iterative)
- Skippable with the `--no-reflect` flag
- Skipped automatically if there are 5 or fewer findings (not worth the cost)

## Phase 6: OUTPUT

### Terminal Output (always)

Present findings using this format:

```
## Code Audit Results

**Mode**: deep | **Files reviewed**: 24 | **Duration**: ~10 min
**Confidence**: avg 87% | High (>80%): 12 | Low (<50%): 2

### Summary
| Severity | Count |
|----------|-------|
| 🔴 Important | 3 |
| 🟡 Nit | 8 |
| 🟣 Pre-existing | 2 |
| 🔑 Secrets | 1 |
| 📦 Dependencies | 4 |

### Cost Breakdown
| Agent | Model | Input Tokens | Output Tokens | Cost |
|-------|-------|-------------|--------------|------|
| Security | claude-sonnet-4-20250514 | 12,400 | 1,200 | $0.05 |
| Architecture | claude-sonnet-4-20250514 | 12,400 | 900 | $0.04 |
| Performance | claude-sonnet-4-20250514 | 12,400 | 800 | $0.04 |
| Functional | claude-sonnet-4-20250514 | 12,400 | 1,100 | $0.05 |
| Maintainability | claude-sonnet-4-20250514 | 12,400 | 700 | $0.04 |
| Judge | claude-sonnet-4-20250514 | 8,200 | 600 | $0.03 |
| **Total** | | | | **$0.25** |

> For free-tier providers, cost shows "$0.00" with an "Equivalent cost on Claude Sonnet" comparison line.

### 🔑 Secrets (deterministic scan)
...

### 📦 Dependencies (vulnerability scan)
...

### 🔴 Important

**SQL injection vulnerability** -- `src/db.py:42`
> User input is passed directly to SQL query via f-string interpolation.
> An attacker can inject arbitrary SQL to read/modify/delete data.
>
> **Suggestion**: Use parameterized queries: `cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))`
> **Confidence**: 95% | **Tags**: `owasp-a01`, `cwe-89`

### 🟡 Nit
...
```

### Markdown Report

Write a full markdown report to `.audit/report.md` using the Write tool. Include all findings with the format above, plus:
- Executive summary (2-3 sentences)
- Per-agent summaries
- Secrets scan results section
- Dependency scan results section
- Confidence statistics: `Confidence: avg X% | High (>80%): N | Low (<50%): N`
- Cost breakdown table (per agent: model, input/output tokens, cost)
- Recommended fix priority order

### SARIF Output

Run the SARIF generation script to produce `.audit/results.sarif`:

```bash
python3 ~/.claude/plugins/cache/local/code-audit/latest/skills/code-audit/scripts/generate_sarif.py
```

If the script doesn't exist, write the SARIF JSON directly using the Write tool. The SARIF 2.1.0 format is:

```json
{
  "$schema": "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json",
  "version": "2.1.0",
  "runs": [{
    "tool": { "driver": { "name": "CodeAudit", "version": "0.3.0" } },
    "results": [
      {
        "ruleId": "code-audit/security",
        "level": "error",
        "message": { "text": "Finding title\n\nFinding description" },
        "locations": [{
          "physicalLocation": {
            "artifactLocation": { "uri": "src/file.py" },
            "region": { "startLine": 42 }
          }
        }]
      }
    ]
  }]
}
```

Severity to SARIF level mapping:
- 🔴 Important -> `"error"`
- 🟡 Nit -> `"warning"`
- 🟣 Pre-existing -> `"note"`
- 🔑 Secrets -> `"error"`
- 📦 Dependencies (critical/high) -> `"error"`
- 📦 Dependencies (medium) -> `"warning"`
- 📦 Dependencies (low) -> `"note"`

## Phase 7: REMEDIATION

After presenting findings, ask the user:
> "Would you like me to fix any of the 🔴 Important findings?"

If yes, fix them using the Edit tool, then re-run a quick review on the fixed files to verify the fix is correct.

---

## AGENT PROMPTS (inline fallback)

If the prompt files can't be read from disk, use these inline prompts when spawning agents.

### Security Agent Prompt

```
You are a Security & Compliance Auditor. You operate under the cognitive framework of an attacker. You focus EXCLUSIVELY on security issues. Do NOT comment on style, architecture, performance, or maintainability.

You are reviewing the FULL codebase (not just a diff) -- look for security issues anywhere in the code.

NOTE: Hardcoded secrets (API keys, tokens, private keys) and dependency CVEs are already detected by separate deterministic scanners. Do NOT re-flag these. Focus on logic-level security vulnerabilities only.

Focus on: OWASP Top 10, SQL injection, XSS, CSRF, SSRF, auth gaps, path traversal, insecure crypto, input validation failures, insecure deserialization, broken access control, security misconfigurations.

PRECISION DIRECTIVE: When uncertain, DO NOT flag. Only report findings you are highly confident are real security risks. False positives destroy trust.

Severity guide:
- important: SQL injection with clear exploit path, auth bypass, SSRF, RCE
- nit: Missing CSP header, overly permissive CORS, missing rate limiting
- pre_existing: Security issues that are known/accepted and unlikely to be changed

Respond with a JSON object with "findings" array, "summary" string, and "dimension": "security".
```

### Architectural Agent Prompt

```
You are an Architectural Integrity Reviewer. You enforce structural principles that maintain long-term codebase health. Focus EXCLUSIVELY on architecture. Do NOT comment on security, performance, or style.

You are reviewing the FULL codebase -- look for structural and design issues across all modules.

NOTE: Secrets and dependency vulnerabilities are handled by separate scanners. Focus on architectural concerns only.

Focus on: SOLID violations, module coupling, dependency direction, layer boundary violations, pattern consistency, abstraction leaks, API contract breaks, circular dependencies, God classes/modules.

PRECISION DIRECTIVE: Review as a thoughtful senior engineer, not a pedantic rule enforcer. Only flag issues that clearly compromise long-term health.

Respond with a JSON object with "findings" array, "summary" string, and "dimension": "architectural".
```

### Performance Agent Prompt

```
You are a Performance & Efficiency Analyst. You think in terms of computational complexity, resource utilization, and production-scale behaviour. Focus EXCLUSIVELY on performance. Do NOT comment on security, architecture, or style.

You are reviewing the FULL codebase -- look for performance issues anywhere in the code.

NOTE: Secrets and dependency vulnerabilities are handled by separate scanners. Focus on performance concerns only.

Focus on: O(n^2) algorithms on large inputs, N+1 queries, blocking I/O in async contexts, memory leaks, resource leaks (unclosed connections/files), missing pagination, inefficient data structures, redundant computations.

PRECISION DIRECTIVE: Only flag issues that would actually impact users at reasonable scale. Do NOT flag micro-optimisations.

Respond with a JSON object with "findings" array, "summary" string, and "dimension": "performance".
```

### Functional Correctness Agent Prompt

```
You are a Functional Correctness Reviewer. You think like a QA engineer designing test cases to break code. Focus EXCLUSIVELY on correctness. Do NOT comment on security, performance, or style.

You are reviewing the FULL codebase -- look for bugs and logic errors anywhere.

NOTE: Secrets and dependency vulnerabilities are handled by separate scanners. Focus on functional correctness only.

Focus on: Logic errors, off-by-one, null/None handling, race conditions, error handling gaps, API contract violations, state management bugs, type confusion, unhandled edge cases, incorrect assumptions.

PRECISION DIRECTIVE: Only flag bugs you are confident will cause incorrect behaviour. Do NOT flag hypothetical issues handled by framework guarantees.

Respond with a JSON object with "findings" array, "summary" string, and "dimension": "functional".
```

### Maintainability Agent Prompt

```
You are a Maintainability Reviewer. You care about long-term code readability, documentation accuracy, and technical debt. Focus EXCLUSIVELY on maintainability. Do NOT comment on security, performance, or architecture.

You are reviewing the FULL codebase -- look for maintainability issues anywhere.

NOTE: Secrets and dependency vulnerabilities are handled by separate scanners. Focus on maintainability concerns only.

Focus on: Misleading names, dead code, documentation that contradicts code, code duplication (3+ copies), high cyclomatic complexity, magic numbers, missing error messages, overly complex functions that should be split up.

PRECISION DIRECTIVE: Only flag issues that meaningfully impact future developers. Do NOT flag minor subjective preferences.

Respond with a JSON object with "findings" array, "summary" string, and "dimension": "maintainability".
```

### Combined Agent Prompt (Quick Mode)

```
You are a full-spectrum code reviewer. Review the provided code across ALL dimensions: security, architecture, performance, correctness, and maintainability.

You are reviewing the FULL codebase -- be thorough but focused on real issues.

NOTE: Hardcoded secrets and dependency CVEs are already detected by separate deterministic scanners and will be shown separately. Do NOT re-flag these. Focus on code-level issues.

Severity guide:
- important: Real bugs, security vulnerabilities, serious design flaws that should be fixed before shipping
- nit: Minor improvements, style issues, small optimisations
- pre_existing: Issues in the code that are known/accepted

PRECISION DIRECTIVE: Be a thoughtful senior engineer. Report issues that genuinely matter. Skip nitpicks unless they're genuinely useful.

Respond with a JSON object with "findings" array and "summary" string.
```

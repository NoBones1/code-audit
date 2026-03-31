# CodeAudit — AI Code Review for VS Code

Multi-agent AI code review with 5 specialist agents that review your code across security, architecture, performance, correctness, and maintainability.

## Features

- **Quick Review** — Single-pass review of uncommitted changes
- **Deep Review** — 5 parallel specialist agents + judge aggregation
- **Security Review** — Security-focused audit only
- **Inline Diagnostics** — Findings appear as squiggly lines in the editor
- **Sidebar Panel** — Browse findings by severity and dimension
- **Dismiss Findings** — Dismissed findings are remembered across reviews
- **SARIF Support** — Reads `.audit/results.sarif` for findings

## Requirements

- The `code-audit` CLI must be installed (`pip install code-audit`)
- An `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` environment variable

## Commands

| Command | Description |
|---------|-------------|
| `CodeAudit: Quick Review` | Fast single-pass review |
| `CodeAudit: Deep Review` | Full 5-agent parallel review |
| `CodeAudit: Security Review` | Security-only audit |
| `CodeAudit: Dismiss Finding` | Suppress a finding in future reviews |
| `CodeAudit: Open Last Report` | Open the markdown report |

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `codeAudit.pythonPath` | `code-audit` | Path to CLI executable |
| `codeAudit.defaultMode` | `quick` | Default review mode |
| `codeAudit.autoReviewOnSave` | `false` | Auto-review on save |
| `codeAudit.diffTarget` | `HEAD` | Git ref to diff against |

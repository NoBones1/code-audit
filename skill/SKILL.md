---
name: code-audit
description: >
  Run a multi-agent AI code review on the current project. Analyzes code across
  5 dimensions (security, architecture, performance, correctness, maintainability)
  using parallel specialist agents and a judge aggregator. Supports quick scan,
  deep audit, and security-only modes. Outputs to terminal, markdown, and SARIF.
  Trigger on: "review code", "audit code", "code review", "check for bugs",
  "security review", "review my changes", "review this PR", "code audit",
  "check my code", "find bugs", "review before merge".
user-invocable: true
---

# CodeAudit: Multi-Agent Code Review

Run a comprehensive AI-powered code review on the current project using the CodeAudit CLI tool.

## Prerequisites

The `code-audit` CLI must be installed. If not installed, run:

```bash
cd "/Users/lokeshsoni/Documents/Claude Code/Prompt Builder/code-audit" && pip install -e .
```

## Usage

### Step 1: Determine the review scope

Ask the user what they want to review:
- **Current changes** (default): Reviews uncommitted changes against HEAD
- **Branch diff**: Reviews all changes vs a target branch (e.g., `--diff-target main`)
- **Full project**: Set diff-target to the initial commit

### Step 2: Choose the review mode

- **Quick** (`--mode quick`): Single combined agent, ~2-5 minutes. Best for active development.
- **Deep** (`--mode deep`): 5 parallel specialist agents + judge aggregation, ~15-20 minutes. Best for pre-merge reviews.
- **Security** (`--mode security`): Security agent only, ~3-5 minutes. Best for security-focused checks.

### Step 3: Run the audit

```bash
code-audit review --mode {mode} --diff-target {target} --path {project_path}
```

### Step 4: Read and present the results

After the audit completes, read the markdown report:

```bash
cat {project_path}/.audit/report.md
```

Present the findings to the user with severity indicators:
- 🔴 **Important**: Must fix before merging
- 🟡 **Nit**: Worth fixing but not blocking
- 🟣 **Pre-existing**: Issues not introduced by current changes

### Step 5: Offer to fix Important findings

For each 🔴 Important finding, offer to implement the suggested fix. Use the Edit tool
to apply fixes directly to the source files.

## Configuration

The tool reads `audit.config.yaml` from the project root. If none exists, suggest running:

```bash
code-audit init --path {project_path}
```

This creates both `audit.config.yaml` and `REVIEW.md` templates for the user to customize.

## Environment Variables

The tool requires an API key set as an environment variable:
- Claude: `ANTHROPIC_API_KEY`
- Gemini: `GEMINI_API_KEY`

Check that the appropriate key is set before running.

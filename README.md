# CodeAudit

Multi-agent AI code review tool that analyzes code across 5 dimensions using parallel specialist agents.

## Quick Start

```bash
# Install
pip install -e .

# Review current changes (deep mode)
code-audit review

# Quick scan
code-audit review --mode quick

# Security-only review
code-audit review --mode security

# Review against a branch
code-audit review --diff-target main

# Initialize config for a project
code-audit init
```

## Review Modes

| Mode | Agents | Time | Use Case |
|------|--------|------|----------|
| quick | 1 combined | ~2-5 min | Active development |
| deep | 5 parallel + Judge | ~15-20 min | Pre-merge review |
| security | 1 security | ~3-5 min | Security audit |

## Configuration

Place `audit.config.yaml` and `REVIEW.md` in your project root. Run `code-audit init` to generate templates.

## Requirements

- Python 3.11+
- An API key for Claude (`ANTHROPIC_API_KEY`) or Gemini (`GEMINI_API_KEY`)

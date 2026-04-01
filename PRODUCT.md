# CodeAudit: Product Overview & Competitive Analysis

**Last updated**: 2026-04-01
**Status**: Phase 2 complete, Phase 3 in planning
**Repos**: [NoBones1/code-audit](https://github.com/NoBones1/code-audit) | [NoBones1/prompt-builder](https://github.com/NoBones1/prompt-builder)

---

## What CodeAudit Does

Multi-agent AI code review tool that spawns 5 specialist agents in parallel (security, architecture, performance, correctness, maintainability), aggregates findings through a judge pass, and outputs severity-ranked results with remediation suggestions.

**Three ways to use it:**
1. **Claude Code plugin** — type `/code-audit` in any project (uses Max plan subscription, $0 extra)
2. **Python CLI** — `code-audit review` from terminal (uses NVIDIA/Gemini/OpenRouter free tier, $0)
3. **GitHub integration** — auto-reviews PRs on open/sync, posts inline comments

---

## Feature Inventory

### Built & Working

| Feature | Description | Status |
|---------|-------------|--------|
| 5 specialist agents + judge | Security, architectural, performance, functional, maintainability | ✅ Live |
| Quick mode (single agent) | Fast combined review, 2-3 min | ✅ Live |
| Deep mode (5 parallel + judge) | Full review, 8-15 min | ✅ Live |
| Security-only mode | Single-dimension focused review | ✅ Live |
| Full codebase audit | Reviews all source files, not just diffs | ✅ Live |
| Diff review | Reviews uncommitted changes or branch diffs | ✅ Live |
| SARIF 2.1.0 output | Machine-readable results for CI/CD | ✅ Live |
| Markdown reports | `.audit/report.md` with full findings | ✅ Live |
| Rich terminal output | Color-coded, severity-ranked display | ✅ Live |
| Tree-sitter code graph | Dependency/impact analysis (Python, TS, JS) | ✅ Live |
| Claude Code plugin | `/code-audit` slash command, uses Max plan | ✅ Live |
| NVIDIA Kimi K2.5 default | Best code reasoning model, free tier | ✅ Live |
| Provider fallback chain | NVIDIA -> Gemini -> OpenRouter, auto-failover | ✅ Live |
| Per-agent LLM overrides | Different models per agent via config | ✅ Live |
| REVIEW.md rules | Skip patterns, mandatory checks, style rules | ✅ Live |
| CLAUDE.md context | Project context injected into agent prompts | ✅ Live |
| GitHub PR inline comments | Posts findings as review comments on PR lines | ✅ Built |
| GitHub check runs | Creates check run with annotations on PRs | ✅ Built |
| GitHub Actions workflow | Auto-trigger on PR open/sync + comment commands | ✅ Built |
| SARIF upload to GitHub | Findings in Security -> Code Scanning dashboard | ✅ Built |
| Webhook server | FastAPI server for GitHub event handling | ✅ Built |
| Persistent memory | Learns team preferences, suppresses dismissed findings | ✅ Built |
| VS Code extension | Sidebar panel, inline diagnostics, dismiss action | ✅ Packaged (.vsix) |
| 119 unit tests | Diff parsing, config, memory, SARIF, agent response | ✅ All passing |
| Project config system | YAML/JSON with per-project and global config | ✅ Live |
| `code-audit init` | Generates starter config file | ✅ Live |

### Planned (Phase 3)

| Feature | Description | Priority |
|---------|-------------|----------|
| Cost tracking per review | Token counts + $ breakdown per agent, free/paid distinction | Build next |
| Secrets & credential scan | Regex pre-pass: AWS keys, GitHub tokens, passwords, entropy | Build next |
| Dependency vulnerability scan | npm audit, pip-audit, osv-scanner integration (SCA) | Build next |
| Tree-sitter Go/Rust/Java | Expand dependency analysis to 6 languages | Build next |
| REVIEW.md template generator | Smart, framework-aware template on `code-audit init` | Build next |
| Confidence stats display | Average confidence, high/low counts in reports | Build next |
| Agent self-reflection loop | Cross-agent reflection to reduce false positives | Build next |

### Future (Phase 4+)

| Feature | Description | Priority |
|---------|-------------|----------|
| Web dashboard | FastAPI + React for team visibility and trends | Medium |
| Auto-fix with sandbox | Apply fixes, run tests in container, verify before commit | Medium |
| SWE-bench benchmarks | Publish F1 accuracy numbers | Medium |
| SOC2/ISO27001 mapping | Map findings to compliance framework controls | Low |
| Real-time IDE feedback | Language server for live diagnostics | Low |
| Publish as web service | Multi-tenant SaaS with auth and billing | Low |

---

## Competitive Analysis

### Market Landscape (2026)

| Tool | Pricing | Multi-Agent | SARIF | PR Comments | Secrets | SCA | Memory | IDE |
|------|---------|-------------|-------|-------------|---------|-----|--------|-----|
| **CodeAudit (us)** | $0 (free tier) | ✅ 5 agents + judge | ✅ | ✅ | 🔜 Phase 3 | 🔜 Phase 3 | ✅ | ✅ VS Code |
| **Claude Code Review** | ~$15-25/review | ✅ Multi-pass | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **CodeRabbit** | $24/dev/month | ❌ Single-agent | ❌ | ✅ | ✅ | ✅ (Snyk) | ❌ | ❌ |
| **Qodo (CodiumAI)** | $19/dev/month | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ JetBrains |
| **Amazon CodeGuru** | $0.50/100 LOC | ❌ | ❌ | ✅ | ✅ (Detector) | ❌ | ❌ | ❌ |
| **Snyk Code** | $25+/dev/month | ❌ | ✅ | ✅ | ✅ | ✅ (core) | ❌ | ✅ |
| **SonarQube** | Free/Paid | ❌ Rule-based | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ |

### Where We Win

1. **Cost**: $0.00 per review on free-tier providers. Competitors charge $19-25/dev/month.
2. **Multi-agent depth**: 5 independent specialists + judge aggregation. Only Claude Code Review comes close.
3. **SARIF output**: Only us and Snyk produce SARIF 2.1.0 for CI/CD integration.
4. **Persistent memory**: We learn team preferences over time. No competitor does this.
5. **Full codebase audit**: Not just PR diffs — can audit an entire completed project.
6. **Model flexibility**: NVIDIA, Gemini, OpenRouter, Claude, any OpenAI-compatible endpoint. Not locked to one provider.
7. **Self-hosted**: Runs locally, no data leaves your machine (unless you use cloud LLMs).

### Where Competitors Win (Current Gaps)

| Gap | Competitor | Our Status | Phase |
|-----|-----------|------------|-------|
| Secrets scanning | CodeRabbit, Snyk, SonarQube | Building Phase 3 | 🔜 |
| Dependency CVE scanning | CodeRabbit (Snyk), Snyk Code | Building Phase 3 | 🔜 |
| Cost visibility | None (unique to us) | Building Phase 3 | 🔜 |
| Go/Rust/Java tree-sitter | N/A | Building Phase 3 | 🔜 |
| Auto-fix verification | Qodo (test generation) | Phase 4 | 📋 |
| Web dashboard | SonarQube, Snyk | Phase 4 | 📋 |
| SOC2/compliance mapping | Snyk, Veracode | Phase 4+ | 📋 |

### After Phase 3 Completion

With Phase 3 features built, CodeAudit will have **feature parity or superiority** vs every competitor except:
- Snyk's deep SCA database (their core competency — we use their free tools as inputs)
- SonarQube's 5000+ static analysis rules (rule-based, not AI)
- Veracode's compliance certification mappings (enterprise niche)

---

## Architecture Summary

```
User -> Claude Code Plugin (/code-audit)  -> Agent tool (Max plan, $0)
     -> Python CLI (code-audit review)    -> NVIDIA/Gemini/OpenRouter ($0)
     -> GitHub webhook (PR events)        -> CLI under the hood

Pipeline:
Phase 0:    Secrets Scan          (regex, $0.00)            [Phase 3]
Phase 0.5:  Dependency Scan       (npm audit etc, $0.00)    [Phase 3]
Phase 1:    Context Gathering     (git, tree-sitter, REVIEW.md)
Phase 2:    5 Specialist Agents   (parallel, LLM)
Phase 3:    Judge Aggregation     (dedup, filter, rank)
Phase 3.5:  Reflection Loop       (cross-agent, 1 round)    [Phase 3]
Phase 4:    Output                (terminal + markdown + SARIF + cost)
```

---

## Cost Model

### For Users

| Provider | Model | Cost per review | Notes |
|----------|-------|----------------|-------|
| NVIDIA Build | Kimi K2.5 | $0.00 | Free tier, 30 RPM, 5000 RPD, expires 2026-09-28 |
| Gemini | gemini-2.5-flash | $0.00 | Free tier, 8 RPM, 1400 RPD |
| OpenRouter | llama-3.3-70b | $0.00 | Free tier, 18 RPM, 1000 RPD |
| Claude (Anthropic) | claude-sonnet-4-6 | ~$0.14 | $3/1M input, $15/1M output |
| Claude (Anthropic) | claude-opus-4-6 | ~$0.70 | $15/1M input, $75/1M output |

### For SaaS (Future)

Estimated unit economics for a hosted service:
- Deep review (5 agents + judge): ~$0.44-0.74 on Claude Sonnet
- Quick review (1 agent): ~$0.08-0.15 on Claude Sonnet
- On free-tier providers: $0.00 (infrastructure costs only)

Competitive pricing model: $9/dev/month (vs $24 CodeRabbit, $25 Snyk)

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| CLI | Typer + Rich |
| Models | Pydantic v2 |
| LLM Primary | NVIDIA Build (Kimi K2.5) |
| LLM Fallback | Gemini 2.5 Flash, OpenRouter |
| Structured Output | Claude: output_config, Gemini: response_json_schema, OpenAI: response_format |
| SARIF | sarif-pydantic |
| AST Analysis | tree-sitter (Python, TypeScript, JavaScript + Go/Rust/Java planned) |
| Config | YAML/JSON |
| State | File-based (.audit/ directory) |
| VS Code | TypeScript extension |
| GitHub | REST API (Octokit pattern), FastAPI webhook |
| Package Manager | uv |
| Tests | pytest (119 tests) |

---

## Commit History

| Hash | Description |
|------|-------------|
| `702a0ff` | Switch default model to Kimi K2.5 |
| `47162b7` | NVIDIA primary provider + fallback chain + 119 unit tests |
| `26bd3c8` | Package VS Code extension as .vsix |
| `4b04979` | Fix 10 bugs found by self-audit |
| `f2a537c` | Fix plugin to audit full codebase by default |
| `4d78a69` | Add tree-sitter code graph analysis |
| `fb11b73` | Phase 2: GitHub PR integration, persistent memory, VS Code extension |
| `606903e` | Phase 1 complete: multi-agent code review engine, CLI, and Claude Code plugin |

---

## Staying Relevant

### Automated Health Checks

To keep the tool relevant as technology evolves:

1. **Model pricing updates** — MODEL_PRICING dict in `usage.py` needs updating when providers change pricing. Check quarterly.
2. **NVIDIA API key expiration** — Current key expires 2026-09-28. Set a reminder to renew.
3. **Tree-sitter grammar updates** — When new language grammars are released, add parsers.
4. **OWASP/CWE updates** — Security agent prompts reference OWASP Top 10. Review annually when new list publishes.
5. **Competitor feature tracking** — Check CodeRabbit, Snyk, Qodo changelogs quarterly for new features we should match.
6. **LLM benchmark monitoring** — When new models beat Kimi K2.5 on SWE-bench, evaluate switching defaults.
7. **Dependency updates** — `uv lock --upgrade` monthly to keep dependencies current.
8. **SARIF spec updates** — Monitor OASIS SARIF TC for spec updates beyond 2.1.0.

### Suggested Recurring Schedule

| Frequency | Task |
|-----------|------|
| Monthly | `uv lock --upgrade`, run tests, check for breaking changes |
| Quarterly | Review MODEL_PRICING, check competitor features, evaluate new LLMs |
| Annually | Update OWASP references in security prompts, review architecture |
| Before expiry | Renew NVIDIA API key (2026-09-28) |

"""Main orchestrator -- coordinates the full audit pipeline.

Pipeline stages:
1. Context gathering (diff, codebase analysis, REVIEW.md)
2. Parallel specialist review (5 agents via asyncio.gather)
3. Judge aggregation (dedup, filter, rank)
4. Output generation (terminal, markdown, SARIF)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

from code_audit.agents.architectural import ArchitecturalAgent
from code_audit.agents.base import BaseReviewAgent
from code_audit.agents.combined import CombinedAgent
from code_audit.agents.functional import FunctionalAgent
from code_audit.agents.judge import JudgeAgent
from code_audit.agents.maintainability import MaintainabilityAgent
from code_audit.agents.performance import PerformanceAgent
from code_audit.agents.security import SecurityAgent
from code_audit.config.models import AuditConfig, ReviewMode
from code_audit.context.codebase import analyze_codebase
from code_audit.context.diff import extract_diffs
from code_audit.context.file_reader import read_changed_files
from code_audit.context.review_md import find_claude_md, parse_review_md
from code_audit.engine.state import AuditState
from code_audit.graph.analyzer import CodeGraphAnalyzer
from code_audit.llm.fallback import FallbackProvider
from code_audit.llm.registry import create_provider
from code_audit.memory.decisions import DecisionTracker
from code_audit.memory.store import ProjectMemory
from code_audit.models.context import ReviewContext
from code_audit.models.finding import Finding
from code_audit.models.report import AuditReport, AuditSummary, DimensionSummary
from code_audit.models.usage import UsageRecord, calculate_cost


# Agent name → Agent class mapping
SPECIALIST_AGENTS: dict[str, type[BaseReviewAgent]] = {
    "security": SecurityAgent,
    "architectural": ArchitecturalAgent,
    "performance": PerformanceAgent,
    "functional": FunctionalAgent,
    "maintainability": MaintainabilityAgent,
}


class Orchestrator:
    """Coordinates the full multi-agent audit pipeline."""

    def __init__(
        self,
        config: AuditConfig,
        project_path: Path,
        on_agent_start: Callable[[str], None] | None = None,
        on_agent_complete: Callable[[str, int, float], None] | None = None,
        on_agent_error: Callable[[str, str], None] | None = None,
    ):
        self.config = config
        self.project_path = project_path.resolve()
        self.state = AuditState(self.project_path, config.output.directory)
        self.memory = ProjectMemory(self.project_path)
        self.decision_tracker = DecisionTracker(self.project_path)

        # Usage tracking
        self._usage_records: list[UsageRecord] = []

        # Callbacks for terminal UI
        self.on_agent_start = on_agent_start or (lambda name: None)
        self.on_agent_complete = on_agent_complete or (lambda name, count, dur: None)
        self.on_agent_error = on_agent_error or (lambda name, err: None)

    async def run(self) -> AuditReport:
        """Execute the full audit pipeline and return the report."""
        audit_id = uuid.uuid4().hex[:8]
        start_time = time.monotonic()

        # Initialize state
        self.state.initialize(audit_id, self.config.model_dump(mode="json"))

        try:
            # Phase 1: Context gathering
            context = self._gather_context()

            if not context.diffs:
                # No changes to review
                report = AuditReport(
                    audit_id=audit_id,
                    target_path=str(self.project_path),
                    mode=self.config.review.mode.value,
                    diff_target=self.config.review.diff_target,
                    summary=AuditSummary(files_reviewed=0),
                    duration_seconds=time.monotonic() - start_time,
                )
                self.state.mark_completed(0, report.duration_seconds)
                return report

            # Phase 0: Secrets scan (deterministic, no LLM cost)
            secrets_findings: list[Finding] = []
            if context.changed_files:
                try:
                    from code_audit.scanners.secrets import SecretsScanner
                    scanner = SecretsScanner()
                    secrets_findings = scanner.scan_files(context.changed_files)
                    if secrets_findings:
                        self.on_agent_start("secrets")
                        self.on_agent_complete("secrets", len(secrets_findings), 0.0)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Secrets scan failed: {e}")

            # Phase 0.5: Dependency vulnerability scan (no LLM cost)
            dep_findings: list[Finding] = []
            try:
                from code_audit.scanners.dependencies import DependencyScanner
                dep_scanner = DependencyScanner(self.project_path)
                if dep_scanner.detect_ecosystems():
                    self.on_agent_start("dependencies")
                    dep_findings = await dep_scanner.scan()
                    self.on_agent_complete("dependencies", len(dep_findings), 0.0)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Dependency scan failed: {e}")

            # Phase 2: Review (quick or deep)
            if self.config.review.mode == ReviewMode.QUICK:
                all_findings, dimension_summaries = await self._run_quick(context)
            elif self.config.review.mode == ReviewMode.SECURITY:
                all_findings, dimension_summaries = await self._run_security_only(context)
            else:
                all_findings, dimension_summaries = await self._run_deep(context)

            # Phase 3: Judge aggregation (deep mode only, with enough findings)
            if self.config.review.mode == ReviewMode.DEEP and len(all_findings) > 3:
                self.on_agent_start("judge")
                self.state.update_agent_status("judge", "running")

                judge_llm_config = self.config.llm_for_agent("judge")
                judge_provider = FallbackProvider(judge_llm_config)
                judge = JudgeAgent(judge_provider)

                final_findings, judge_summary, judge_duration = await judge.judge(
                    all_findings,
                    context.review_rules,
                )

                # Track judge usage
                judge_usage = judge_provider.last_usage
                judge_record = UsageRecord(
                    agent_name="judge",
                    model=judge_provider.model_name,
                    provider=judge_provider.provider_name,
                    input_tokens=judge_usage.get("input_tokens", 0),
                    output_tokens=judge_usage.get("output_tokens", 0),
                    cost_usd=calculate_cost(judge_provider.model_name, judge_usage.get("input_tokens", 0), judge_usage.get("output_tokens", 0)),
                    duration_seconds=judge_duration,
                )
                self._usage_records.append(judge_record)

                self.state.update_agent_status(
                    "judge", "completed", len(final_findings), judge_duration
                )
                self.on_agent_complete("judge", len(final_findings), judge_duration)
            else:
                final_findings = all_findings

            # Phase 3.5: Agent self-reflection (deep mode only, >5 findings)
            if (self.config.review.mode == ReviewMode.DEEP
                    and len(final_findings) > 5
                    and not self.config.review.no_reflect):
                final_findings = await self._run_reflection(final_findings, all_findings)

            final_findings = secrets_findings + dep_findings + final_findings

            # Phase 4: Build report
            total_duration = time.monotonic() - start_time
            providers_used = list({
                FallbackProvider(self.config.llm_for_agent(name)).provider_name
                for name in (["combined"] if self.config.review.mode == ReviewMode.QUICK
                             else list(SPECIALIST_AGENTS.keys()))
                if self.config.is_agent_enabled(name)
            })

            report = AuditReport(
                audit_id=audit_id,
                target_path=str(self.project_path),
                mode=self.config.review.mode.value,
                diff_target=self.config.review.diff_target,
                findings=final_findings,
                summary=AuditSummary.from_findings(
                    final_findings,
                    files_reviewed=len(context.diffs),
                    dimensions=[ds.dimension for ds in dimension_summaries],
                    dimension_details=dimension_summaries,
                ),
                duration_seconds=total_duration,
                review_rules_applied=context.review_rules is not None,
                llm_providers_used=providers_used,
                usage=self._usage_records,
                total_cost_usd=sum(r.cost_usd for r in self._usage_records),
            )

            self.state.save_report(report)
            self.state.mark_completed(len(final_findings), total_duration)

            # Record audit in project memory for trend tracking
            self.decision_tracker.record_audit_completion(report)

            # Apply memory-based suppression (filter previously dismissed findings)
            # Load dismissals once to avoid N reads for N findings
            dismissals = self.decision_tracker.memory.get_dismissals()
            suppressed = []
            retained = []
            for f in report.findings:
                if self.decision_tracker.should_suppress(f, dismissals=dismissals):
                    suppressed.append(f)
                else:
                    retained.append(f)
            if suppressed:
                report.findings = retained
                # Recalculate summary
                report.summary = AuditSummary.from_findings(
                    retained,
                    files_reviewed=report.summary.files_reviewed,
                    dimensions=report.summary.dimensions_run,
                    dimension_details=report.summary.dimension_summaries,
                )

            return report

        except Exception as e:
            self.state.mark_failed(str(e))
            raise

    def _gather_context(self) -> ReviewContext:
        """Phase 1: Gather all context needed for the review."""
        diffs = extract_diffs(self.project_path, self.config.review.diff_target)

        # Filter by include/exclude patterns
        # (basic glob-like filtering)
        filtered_diffs = self._filter_diffs(diffs)

        # Limit file count
        if len(filtered_diffs) > self.config.review.max_files:
            # Prioritize by change count
            filtered_diffs = sorted(
                filtered_diffs, key=lambda d: d.total_changes, reverse=True
            )[:self.config.review.max_files]

        changed_paths = [d.file_path for d in filtered_diffs]
        languages, frameworks, file_tree = analyze_codebase(self.project_path, changed_paths)

        changed_files = read_changed_files(
            self.project_path,
            filtered_diffs,
            max_file_size_kb=self.config.review.max_file_size_kb,
        )

        review_rules = parse_review_md(self.project_path)
        project_context = find_claude_md(self.project_path)

        # Build code graph for dependency analysis
        dependency_context = ""
        resolved_graph = None
        try:
            graph_analyzer = CodeGraphAnalyzer(self.project_path)
            code_graph = graph_analyzer.analyze(
                changed_files=changed_paths,
                include_neighbors=True,
                max_files=30,
            )
            if code_graph.total_symbols > 0:
                dependency_context = code_graph.format_for_prompt(changed_paths)
                resolved_graph = code_graph
        except Exception:
            pass  # Code graph is a nice-to-have, not a blocker

        total_add = sum(d.additions for d in filtered_diffs)
        total_del = sum(d.deletions for d in filtered_diffs)

        return ReviewContext(
            target_path=str(self.project_path),
            languages=languages,
            frameworks=frameworks,
            file_tree=file_tree,
            diffs=filtered_diffs,
            changed_files=changed_files,
            review_rules=review_rules,
            project_context=project_context,
            dependency_context=dependency_context,
            code_graph=resolved_graph,
            diff_target=self.config.review.diff_target,
            total_additions=total_add,
            total_deletions=total_del,
        )

    def _filter_diffs(self, diffs: list) -> list:
        """Filter diffs based on include/exclude glob patterns."""
        import fnmatch

        filtered = []
        for diff in diffs:
            fp = diff.file_path

            # Check exclude patterns first
            excluded = False
            for pattern in self.config.review.exclude:
                # fnmatch doesn't support **, so handle common cases:
                # "**/*.test.*" → match if basename matches "*.test.*"
                # "node_modules/**" → match if path starts with "node_modules/"
                if "**" in pattern:
                    # "prefix/**" → startswith check
                    if pattern.endswith("/**"):
                        prefix = pattern[:-3]
                        if fp.startswith(prefix + "/") or fp == prefix:
                            excluded = True
                            break
                    # "**/suffix" → check basename or subpath
                    elif pattern.startswith("**/"):
                        sub = pattern[3:]
                        if fnmatch.fnmatch(fp, sub) or fnmatch.fnmatch(fp, f"*/{sub}"):
                            excluded = True
                            break
                    # Other ** patterns: try matching both with and without prefix
                    else:
                        simple = pattern.replace("**/", "")
                        if fnmatch.fnmatch(fp, simple) or fnmatch.fnmatch(fp, f"*/{simple}"):
                            excluded = True
                            break
                elif fnmatch.fnmatch(fp, pattern):
                    excluded = True
                    break
            if excluded:
                continue

            # Check include patterns - default to including everything
            if not self.config.review.include or self.config.review.include == ["**/*"]:
                filtered.append(diff)
                continue

            included = False
            for pattern in self.config.review.include:
                if "**" in pattern:
                    if pattern == "**/*":
                        included = True
                        break
                    if pattern.endswith("/**"):
                        prefix = pattern[:-3]
                        if fp.startswith(prefix + "/") or fp == prefix:
                            included = True
                            break
                    elif pattern.startswith("**/"):
                        sub = pattern[3:]
                        if fnmatch.fnmatch(fp, sub) or fnmatch.fnmatch(fp, f"*/{sub}"):
                            included = True
                            break
                elif fnmatch.fnmatch(fp, pattern):
                    included = True
                    break
            if included:
                filtered.append(diff)

        return filtered

    async def _run_quick(self, context: ReviewContext) -> tuple[list[Finding], list[DimensionSummary]]:
        """Run quick mode: single combined agent."""
        agent_name = "combined"
        self.on_agent_start(agent_name)
        self.state.update_agent_status(agent_name, "running")

        llm_config = self.config.llm_for_agent(agent_name)
        provider = FallbackProvider(llm_config)
        memory_ctx = self.memory.format_for_prompt() or None
        agent = CombinedAgent(llm=provider, memory_context=memory_ctx)

        findings, summary, duration = await agent.review(context)

        # Track usage
        usage = provider.last_usage
        record = UsageRecord(
            agent_name=agent_name,
            model=provider.model_name,
            provider=provider.provider_name,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cost_usd=calculate_cost(provider.model_name, usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
            duration_seconds=duration,
        )
        self._usage_records.append(record)

        self.state.save_agent_findings(agent_name, findings)
        self.state.update_agent_status(agent_name, "completed", len(findings), duration)
        self.on_agent_complete(agent_name, len(findings), duration)

        dim_summary = DimensionSummary(
            dimension=agent_name,
            total_findings=len(findings),
            important=sum(1 for f in findings if f.severity.value == "important"),
            nit=sum(1 for f in findings if f.severity.value == "nit"),
            pre_existing=sum(1 for f in findings if f.severity.value == "pre_existing"),
            agent_model=provider.model_name,
            duration_seconds=duration,
            avg_confidence=sum(f.confidence for f in findings) / len(findings) if findings else 0.0,
        )

        return findings, [dim_summary]

    async def _run_security_only(self, context: ReviewContext) -> tuple[list[Finding], list[DimensionSummary]]:
        """Run security-only mode."""
        return await self._run_agents(context, {"security": SecurityAgent})

    async def _run_deep(self, context: ReviewContext) -> tuple[list[Finding], list[DimensionSummary]]:
        """Run deep mode: all 5 specialist agents in parallel."""
        enabled_agents = {
            name: cls for name, cls in SPECIALIST_AGENTS.items()
            if self.config.is_agent_enabled(name)
        }
        return await self._run_agents(context, enabled_agents)

    async def _run_agents(
        self,
        context: ReviewContext,
        agents: dict[str, type[BaseReviewAgent]],
    ) -> tuple[list[Finding], list[DimensionSummary]]:
        """Run agents with a concurrency cap to avoid rate-limit cascades on free providers."""
        semaphore = asyncio.Semaphore(self.config.review.max_concurrency)
        tasks = []
        agent_names = []

        for name, agent_cls in agents.items():
            llm_config = self.config.llm_for_agent(name)
            provider = FallbackProvider(llm_config)

            extra = None
            agent_cfg = self.config.agents.get(name)
            if agent_cfg:
                extra = agent_cfg.extra_instructions

            memory_ctx = self.memory.format_for_prompt() or None
            agent = agent_cls(llm=provider, extra_instructions=extra, memory_context=memory_ctx)

            async def _gated(n=name, a=agent, p=provider):
                async with semaphore:
                    return await self._run_single_agent(n, a, context, provider=p)

            tasks.append(_gated())
            agent_names.append(name)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_findings: list[Finding] = []
        dimension_summaries: list[DimensionSummary] = []

        for name, result in zip(agent_names, results):
            if isinstance(result, Exception):
                self.state.update_agent_status(name, "failed")
                self.on_agent_error(name, str(result))
                continue

            findings, summary, duration = result
            all_findings.extend(findings)

            dimension_summaries.append(DimensionSummary(
                dimension=name,
                total_findings=len(findings),
                important=sum(1 for f in findings if f.severity.value == "important"),
                nit=sum(1 for f in findings if f.severity.value == "nit"),
                pre_existing=sum(1 for f in findings if f.severity.value == "pre_existing"),
                agent_model=FallbackProvider(self.config.llm_for_agent(name)).model_name,
                avg_confidence=sum(f.confidence for f in findings) / len(findings) if findings else 0.0,
                duration_seconds=duration,
            ))

        return all_findings, dimension_summaries

    async def _run_single_agent(
        self,
        name: str,
        agent: BaseReviewAgent,
        context: ReviewContext,
        provider: LLMProvider | None = None,
    ) -> tuple[list[Finding], str, float]:
        """Run a single agent with status tracking."""
        self.on_agent_start(name)
        self.state.update_agent_status(name, "running")

        findings, summary, duration = await agent.review(context)

        # Track usage
        if provider is not None:
            usage = provider.last_usage
            record = UsageRecord(
                agent_name=name,
                model=provider.model_name,
                provider=provider.provider_name,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cost_usd=calculate_cost(provider.model_name, usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
                duration_seconds=duration,
            )
            self._usage_records.append(record)

        self.state.save_agent_findings(name, findings)
        self.state.update_agent_status(name, "completed", len(findings), duration)
        self.on_agent_complete(name, len(findings), duration)

        return findings, summary, duration

    async def _run_reflection(
        self,
        judged_findings: list[Finding],
        raw_findings: list[Finding],
    ) -> list[Finding]:
        """Run one round of cross-agent self-reflection."""
        from code_audit.agents.reflector import ReflectionAgent

        # Group judged findings by dimension
        by_dimension: dict[str, list[Finding]] = {}
        for f in judged_findings:
            by_dimension.setdefault(f.dimension, []).append(f)

        # Only reflect on dimensions that had findings
        tasks = []
        dimensions = []
        for dim, findings in by_dimension.items():
            if dim in ("secrets", "dependencies", "combined"):
                continue  # Skip non-LLM dimensions
            llm_config = self.config.llm_for_agent(dim)
            provider = FallbackProvider(llm_config)
            agent = ReflectionAgent(llm=provider, dimension=dim)

            self.on_agent_start(f"reflect-{dim}")
            tasks.append(agent.reflect(findings, judged_findings))
            dimensions.append((dim, provider))

        if not tasks:
            return judged_findings

        semaphore = asyncio.Semaphore(self.config.review.max_concurrency)
        gated_tasks = []
        for task_coro, (dim, provider) in zip(tasks, dimensions):
            async def _gated_reflect(coro=task_coro):
                async with semaphore:
                    return await coro
            gated_tasks.append(_gated_reflect())

        results = await asyncio.gather(*gated_tasks, return_exceptions=True)

        # Collect updated findings
        reflected_findings: list[Finding] = []
        non_reflected: list[Finding] = []

        reflected_dimensions = set()
        for i, result in enumerate(results):
            dim, provider = dimensions[i]
            if isinstance(result, Exception):
                logger.warning(f"Reflection failed for {dim}: {result}")
                # Keep original findings for this dimension
                reflected_findings.extend(by_dimension[dim])
                self.on_agent_error(f"reflect-{dim}", str(result))
            else:
                updated, duration = result
                reflected_findings.extend(updated)
                reflected_dimensions.add(dim)

                # Track usage
                usage = provider.last_usage
                record = UsageRecord(
                    agent_name=f"reflect-{dim}",
                    model=provider.model_name,
                    provider=provider.provider_name,
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    cost_usd=calculate_cost(provider.model_name, usage.get("input_tokens", 0), usage.get("output_tokens", 0)),
                    duration_seconds=duration,
                )
                self._usage_records.append(record)
                self.on_agent_complete(f"reflect-{dim}", len(updated), duration)

        # Add back findings from dimensions that weren't reflected on
        for f in judged_findings:
            if f.dimension not in reflected_dimensions:
                non_reflected.append(f)

        return reflected_findings + non_reflected

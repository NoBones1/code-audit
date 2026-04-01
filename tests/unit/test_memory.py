"""Unit tests for memory — decisions, store, suppression."""

import json
import pytest
from pathlib import Path

from code_audit.memory.decisions import DecisionTracker
from code_audit.memory.store import (
    ProjectMemory,
    ReviewDecision,
    CodePattern,
    AuditSummaryRecord,
)
from code_audit.models.finding import Finding, FindingLocation, Severity


def _make_finding(
    title: str = "SQL injection",
    dimension: str = "security",
    file_path: str = "src/app.py",
    severity: Severity = Severity.IMPORTANT,
) -> Finding:
    return Finding(
        dimension=dimension,
        severity=severity,
        title=title,
        description="Test description",
        location=FindingLocation(
            file_path=file_path,
            start_line=10,
            snippet="test code",
        ),
        confidence=0.9,
    )


# ── should_suppress ───────────────────────────────────────────────────────

class TestShouldSuppress:
    def test_exact_title_match_suppresses(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        finding = _make_finding(title="SQL injection", dimension="security", file_path="src/app.py")

        # Record a dismissal for the same title+dimension+file
        tracker.record_dismissal(finding, reason="admin-only endpoint", audit_id="audit-1")

        # Now check suppression
        same_finding = _make_finding(title="SQL injection", dimension="security", file_path="src/app.py")
        assert tracker.should_suppress(same_finding) is True

    def test_different_title_not_suppressed(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        finding = _make_finding(title="SQL injection")
        tracker.record_dismissal(finding, reason="ok")

        other = _make_finding(title="XSS vulnerability")
        assert tracker.should_suppress(other) is False

    def test_empty_dismissals_returns_false(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        finding = _make_finding()
        assert tracker.should_suppress(finding) is False

    def test_case_insensitive_title_match(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        finding = _make_finding(title="SQL Injection")
        tracker.record_dismissal(finding, reason="ok")

        lower = _make_finding(title="sql injection")
        assert tracker.should_suppress(lower) is True

    def test_different_dimension_not_suppressed(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        finding = _make_finding(title="Missing timeout", dimension="security")
        tracker.record_dismissal(finding, reason="ok")

        perf_finding = _make_finding(title="Missing timeout", dimension="performance")
        assert tracker.should_suppress(perf_finding) is False

    def test_with_preloaded_dismissals(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        finding = _make_finding(title="SQL injection", dimension="security", file_path="src/app.py")

        dismissals = [
            ReviewDecision(
                finding_title="SQL injection",
                finding_dimension="security",
                file_pattern="src/app.py",
                action="dismissed",
                reason="ok",
            )
        ]

        assert tracker.should_suppress(finding, dismissals=dismissals) is True

    def test_preloaded_empty_list(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        finding = _make_finding()
        assert tracker.should_suppress(finding, dismissals=[]) is False


# ── record_dismissal / record_acceptance ──────────────────────────────────

class TestRecordDecisions:
    def test_record_dismissal_persists(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        finding = _make_finding(title="Hardcoded secret")
        tracker.record_dismissal(finding, reason="dev-only key", audit_id="a1")

        decisions = tracker.memory.load_decisions()
        assert len(decisions) == 1
        assert decisions[0].action == "dismissed"
        assert decisions[0].finding_title == "Hardcoded secret"
        assert decisions[0].reason == "dev-only key"

    def test_record_acceptance_persists(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        finding = _make_finding(title="Missing timeout")
        tracker.record_acceptance(finding, audit_id="a2")

        decisions = tracker.memory.load_decisions()
        assert len(decisions) == 1
        assert decisions[0].action == "accepted"

    def test_multiple_decisions(self, tmp_path):
        tracker = DecisionTracker(tmp_path)
        f1 = _make_finding(title="Issue A")
        f2 = _make_finding(title="Issue B")
        tracker.record_dismissal(f1, reason="ok")
        tracker.record_acceptance(f2)

        decisions = tracker.memory.load_decisions()
        assert len(decisions) == 2


# ── ProjectMemory store ──────────────────────────────────────────────────

class TestProjectMemory:
    def test_empty_store(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        assert mem.load_decisions() == []
        assert mem.load_patterns() == []
        assert mem.load_history() == []

    def test_save_and_load_decision(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        d = ReviewDecision(
            finding_title="Test",
            finding_dimension="security",
            action="dismissed",
        )
        mem.save_decision(d)
        loaded = mem.load_decisions()
        assert len(loaded) == 1
        assert loaded[0].finding_title == "Test"

    def test_get_dismissals_filters(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        mem.save_decision(ReviewDecision(
            finding_title="A", finding_dimension="security", action="dismissed",
        ))
        mem.save_decision(ReviewDecision(
            finding_title="B", finding_dimension="security", action="accepted",
        ))
        dismissals = mem.get_dismissals()
        assert len(dismissals) == 1
        assert dismissals[0].finding_title == "A"

    def test_save_and_load_pattern(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        p = CodePattern(
            pattern_description="f-string SQL",
            dimension="security",
            team_verdict="must_fix",
        )
        mem.save_pattern(p)
        loaded = mem.load_patterns()
        assert len(loaded) == 1
        assert loaded[0].pattern_description == "f-string SQL"

    def test_pattern_occurrence_increment(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        p = CodePattern(
            pattern_description="f-string SQL",
            dimension="security",
            team_verdict="must_fix",
        )
        mem.save_pattern(p)
        mem.save_pattern(p)  # Same description — should increment occurrences
        loaded = mem.load_patterns()
        assert len(loaded) == 1
        assert loaded[0].occurrences == 2

    def test_save_and_load_audit_history(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        record = AuditSummaryRecord(
            audit_id="test-1",
            timestamp="2026-01-01T00:00:00Z",
            mode="quick",
            files_reviewed=5,
            total_findings=3,
            important=1,
            nit=2,
            pre_existing=0,
            duration_seconds=12.5,
        )
        mem.save_audit_summary(record)
        history = mem.load_history()
        assert len(history) == 1
        assert history[0].audit_id == "test-1"

    def test_memory_dir_created(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        assert (tmp_path / ".code-audit" / "memory").is_dir()

    def test_format_for_prompt_empty(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        assert mem.format_for_prompt() == ""

    def test_format_for_prompt_with_dismissals(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        mem.save_decision(ReviewDecision(
            finding_title="SQL injection",
            finding_dimension="security",
            file_pattern="src/app.py",
            action="dismissed",
            reason="admin only",
        ))
        prompt = mem.format_for_prompt()
        assert "SQL injection" in prompt
        assert "admin only" in prompt

    def test_get_dismissal_patterns(self, tmp_path):
        mem = ProjectMemory(tmp_path)
        mem.save_decision(ReviewDecision(
            finding_title="Hardcoded secret",
            finding_dimension="security",
            action="dismissed",
            reason="dev key",
        ))
        patterns = mem.get_dismissal_patterns()
        assert len(patterns) == 1
        assert "Hardcoded secret" in patterns[0]

"""Unit tests for usage tracking and cost calculation."""

import pytest

from code_audit.models.usage import (
    AuditUsageSummary,
    UsageRecord,
    calculate_cost,
    get_pricing,
)


# ── get_pricing ──────────────────────────────────────────────────────────────

class TestGetPricing:
    def test_exact_match_claude_sonnet(self):
        input_rate, output_rate, note = get_pricing("claude-sonnet-4-6")
        assert input_rate == 3.0
        assert output_rate == 15.0
        assert note == "per 1M tokens"

    def test_exact_match_free_tier(self):
        input_rate, output_rate, note = get_pricing("gemini-2.5-flash")
        assert input_rate == 0.0
        assert output_rate == 0.0
        assert "free" in note.lower()

    def test_exact_match_nvidia_free(self):
        input_rate, output_rate, note = get_pricing("moonshotai/kimi-k2.5")
        assert input_rate == 0.0
        assert output_rate == 0.0
        assert "NVIDIA" in note

    def test_partial_match(self):
        """A model string containing a known key should match."""
        input_rate, output_rate, note = get_pricing("claude-sonnet-4-6-20250514")
        # "claude-sonnet-4-6" is contained in the lookup key check
        assert input_rate == 3.0
        assert output_rate == 15.0

    def test_unknown_model_returns_free(self):
        input_rate, output_rate, note = get_pricing("some-unknown-model-xyz")
        assert input_rate == 0.0
        assert output_rate == 0.0
        assert "unknown" in note.lower()


# ── calculate_cost ───────────────────────────────────────────────────────────

class TestCalculateCost:
    def test_free_model_zero_cost(self):
        cost = calculate_cost("gemini-2.5-flash", input_tokens=50000, output_tokens=10000)
        assert cost == 0.0

    def test_paid_model_correct_cost(self):
        # claude-sonnet-4-6: $3/1M input, $15/1M output
        cost = calculate_cost("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000)
        assert cost == pytest.approx(18.0)

    def test_paid_model_small_usage(self):
        # 1000 input tokens, 500 output tokens on claude-sonnet-4-6
        cost = calculate_cost("claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
        expected = (1000 * 3.0 / 1_000_000) + (500 * 15.0 / 1_000_000)
        assert cost == pytest.approx(expected)

    def test_zero_tokens(self):
        cost = calculate_cost("claude-opus-4-6", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_unknown_model_free(self):
        cost = calculate_cost("unknown-model", input_tokens=100000, output_tokens=50000)
        assert cost == 0.0


# ── UsageRecord ──────────────────────────────────────────────────────────────

class TestUsageRecord:
    def _make_record(self, **kwargs) -> UsageRecord:
        defaults = {
            "agent_name": "security",
            "model": "gemini-2.5-flash",
            "provider": "gemini",
            "input_tokens": 5000,
            "output_tokens": 2000,
            "cost_usd": 0.0,
            "duration_seconds": 3.5,
        }
        defaults.update(kwargs)
        return UsageRecord(**defaults)

    def test_total_tokens(self):
        record = self._make_record(input_tokens=5000, output_tokens=2000)
        assert record.total_tokens == 7000

    def test_is_free_when_zero_cost(self):
        record = self._make_record(cost_usd=0.0)
        assert record.is_free is True

    def test_is_free_when_paid(self):
        record = self._make_record(cost_usd=0.05, model="claude-sonnet-4-6")
        assert record.is_free is False

    def test_pricing_note_known_model(self):
        record = self._make_record(model="gemini-2.5-flash")
        assert "free" in record.pricing_note.lower()

    def test_pricing_note_paid_model(self):
        record = self._make_record(model="claude-sonnet-4-6")
        assert record.pricing_note == "per 1M tokens"

    def test_format_display_free(self):
        record = self._make_record(cost_usd=0.0)
        display = record.format_display()
        assert "security" in display
        assert "$0.00" in display
        assert "5,000" in display

    def test_format_display_paid(self):
        record = self._make_record(
            model="claude-sonnet-4-6",
            cost_usd=0.05,
            input_tokens=10000,
            output_tokens=3000,
        )
        display = record.format_display()
        assert "$0.05" in display
        assert "10,000" in display


# ── AuditUsageSummary ────────────────────────────────────────────────────────

class TestAuditUsageSummary:
    def _make_summary(self, records: list[UsageRecord] | None = None) -> AuditUsageSummary:
        if records is None:
            records = [
                UsageRecord(
                    agent_name="security",
                    model="gemini-2.5-flash",
                    provider="gemini",
                    input_tokens=5000,
                    output_tokens=2000,
                    cost_usd=0.0,
                ),
                UsageRecord(
                    agent_name="performance",
                    model="gemini-2.5-flash",
                    provider="gemini",
                    input_tokens=3000,
                    output_tokens=1500,
                    cost_usd=0.0,
                ),
            ]
        return AuditUsageSummary(records=records)

    def test_total_input_tokens(self):
        summary = self._make_summary()
        assert summary.total_input_tokens == 8000

    def test_total_output_tokens(self):
        summary = self._make_summary()
        assert summary.total_output_tokens == 3500

    def test_total_tokens(self):
        summary = self._make_summary()
        assert summary.total_tokens == 11500

    def test_total_cost_usd_all_free(self):
        summary = self._make_summary()
        assert summary.total_cost_usd == 0.0

    def test_total_cost_usd_mixed(self):
        records = [
            UsageRecord(
                agent_name="security",
                model="gemini-2.5-flash",
                provider="gemini",
                input_tokens=5000,
                output_tokens=2000,
                cost_usd=0.0,
            ),
            UsageRecord(
                agent_name="judge",
                model="claude-sonnet-4-6",
                provider="claude",
                input_tokens=10000,
                output_tokens=3000,
                cost_usd=0.075,
            ),
        ]
        summary = self._make_summary(records)
        assert summary.total_cost_usd == pytest.approx(0.075)

    def test_all_free_true(self):
        summary = self._make_summary()
        assert summary.all_free is True

    def test_all_free_false(self):
        records = [
            UsageRecord(
                agent_name="judge",
                model="claude-sonnet-4-6",
                provider="claude",
                input_tokens=10000,
                output_tokens=3000,
                cost_usd=0.075,
            ),
        ]
        summary = self._make_summary(records)
        assert summary.all_free is False

    def test_equivalent_cost(self):
        summary = self._make_summary()
        # 8000 input + 3500 output on claude-sonnet-4-6: $3/1M * 8000 + $15/1M * 3500
        expected = (8000 * 3.0 / 1_000_000) + (3500 * 15.0 / 1_000_000)
        assert summary.equivalent_cost("claude-sonnet-4-6") == pytest.approx(expected)

    def test_equivalent_cost_different_model(self):
        summary = self._make_summary()
        # On claude-opus-4-6: $15/1M * 8000 + $75/1M * 3500
        expected = (8000 * 15.0 / 1_000_000) + (3500 * 75.0 / 1_000_000)
        assert summary.equivalent_cost("claude-opus-4-6") == pytest.approx(expected)

    def test_empty_summary(self):
        summary = AuditUsageSummary(records=[])
        assert summary.total_tokens == 0
        assert summary.total_cost_usd == 0.0
        assert summary.all_free is True

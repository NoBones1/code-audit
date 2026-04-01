"""Tests for the agent self-reflection loop."""
import pytest
from code_audit.models.reflection_response import ReflectionAction, FindingReflection, ReflectionResponse
from code_audit.models.finding import Finding, FindingLocation, Severity


class TestReflectionResponse:
    def test_keep_action(self):
        r = FindingReflection(finding_id="abc123", action=ReflectionAction.KEEP)
        assert r.action == ReflectionAction.KEEP
        assert r.new_confidence is None

    def test_upgrade_action(self):
        r = FindingReflection(finding_id="abc123", action=ReflectionAction.UPGRADE, new_confidence=0.95)
        assert r.new_confidence == 0.95

    def test_downgrade_action(self):
        r = FindingReflection(finding_id="abc123", action=ReflectionAction.DOWNGRADE, new_confidence=0.3)
        assert r.new_confidence == 0.3

    def test_withdraw_action(self):
        r = FindingReflection(finding_id="abc123", action=ReflectionAction.WITHDRAW, reason="Duplicate of finding xyz")
        assert r.reason == "Duplicate of finding xyz"

    def test_cross_references(self):
        r = FindingReflection(finding_id="abc123", action=ReflectionAction.KEEP, cross_references=["def456", "ghi789"])
        assert len(r.cross_references) == 2

    def test_full_response(self):
        resp = ReflectionResponse(
            reflections=[
                FindingReflection(finding_id="a", action=ReflectionAction.KEEP),
                FindingReflection(finding_id="b", action=ReflectionAction.WITHDRAW, reason="False positive"),
            ],
            summary="1 kept, 1 withdrawn",
        )
        assert len(resp.reflections) == 2
        assert resp.summary == "1 kept, 1 withdrawn"

    def test_confidence_bounds(self):
        # Should not accept confidence > 1.0
        with pytest.raises(Exception):
            FindingReflection(finding_id="a", action=ReflectionAction.UPGRADE, new_confidence=1.5)

    def test_confidence_bounds_low(self):
        # Should not accept confidence < 0.0
        with pytest.raises(Exception):
            FindingReflection(finding_id="a", action=ReflectionAction.DOWNGRADE, new_confidence=-0.1)

    def test_empty_response(self):
        resp = ReflectionResponse()
        assert len(resp.reflections) == 0
        assert resp.summary == ""


class TestReflectionActions:
    """Test that ReflectionAction enum values match expected strings."""
    def test_action_values(self):
        assert ReflectionAction.KEEP.value == "keep"
        assert ReflectionAction.UPGRADE.value == "upgrade"
        assert ReflectionAction.DOWNGRADE.value == "downgrade"
        assert ReflectionAction.WITHDRAW.value == "withdraw"

"""Unit tests for config loading and models."""

import pytest
import yaml
from pathlib import Path

from code_audit.config.loader import load_config, find_project_config, deep_merge, load_yaml_or_json
from code_audit.config.models import (
    AuditConfig,
    LLMConfig,
    LLMProvider,
    ReviewConfig,
    ReviewMode,
    OutputConfig,
    OutputFormat,
    AgentConfig,
)


# ── Default config ────────────────────────────────────────────────────────

class TestDefaultConfig:
    def test_default_config_loads(self):
        config = AuditConfig()
        assert config.llm.provider == LLMProvider.NVIDIA
        assert config.review.mode == ReviewMode.DEEP
        assert config.review.diff_target == "HEAD"
        assert config.review.include == ["**/*"]
        assert "node_modules/**" in config.review.exclude
        assert OutputFormat.SARIF in config.output.formats

    def test_load_config_no_file(self, tmp_path):
        """Loading config from a dir with no config file returns defaults."""
        config = load_config(project_path=tmp_path)
        assert config.review.mode == ReviewMode.DEEP
        assert config.llm.provider == LLMProvider.NVIDIA

    def test_load_config_with_mode_override(self, tmp_path):
        config = load_config(project_path=tmp_path, mode=ReviewMode.QUICK)
        assert config.review.mode == ReviewMode.QUICK

    def test_load_config_with_diff_target_override(self, tmp_path):
        config = load_config(project_path=tmp_path, diff_target="main")
        assert config.review.diff_target == "main"


# ── Config file loading ───────────────────────────────────────────────────

class TestConfigFileLoading:
    def test_find_project_config_yaml(self, tmp_path):
        cfg = tmp_path / ".code-audit.yml"
        cfg.write_text("review:\n  mode: quick\n")
        found = find_project_config(tmp_path)
        assert found is not None
        assert found.name == ".code-audit.yml"

    def test_find_project_config_none(self, tmp_path):
        assert find_project_config(tmp_path) is None

    def test_load_yaml_config(self, tmp_path):
        cfg = tmp_path / ".code-audit.yml"
        cfg.write_text(yaml.dump({"review": {"mode": "quick"}}))
        config = load_config(project_path=tmp_path)
        assert config.review.mode == ReviewMode.QUICK

    def test_load_json_config(self, tmp_path):
        import json
        cfg = tmp_path / "audit.config.json"
        cfg.write_text(json.dumps({"review": {"mode": "security"}}))
        config = load_config(project_path=tmp_path)
        assert config.review.mode == ReviewMode.SECURITY

    def test_malformed_config_falls_back(self, tmp_path):
        cfg = tmp_path / ".code-audit.yml"
        cfg.write_text("review:\n  mode: nonexistent_mode\n")
        config = load_config(project_path=tmp_path)
        # Falls back to defaults due to ValidationError
        assert config.review.mode == ReviewMode.DEEP


# ── Config model validation ───────────────────────────────────────────────

class TestConfigModels:
    def test_valid_llm_config(self):
        cfg = LLMConfig(provider="claude", model="claude-sonnet-4-6", temperature=0.5)
        assert cfg.provider == LLMProvider.CLAUDE
        assert cfg.temperature == 0.5

    def test_temperature_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LLMConfig(temperature=-0.1)
        with pytest.raises(ValidationError):
            LLMConfig(temperature=2.5)

    def test_max_tokens_minimum(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LLMConfig(max_tokens=100)  # Below 256 minimum

    def test_review_config_max_files(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ReviewConfig(max_files=0)  # Below 1 minimum

    def test_agent_config_with_llm_override(self):
        config = AuditConfig(
            agents={
                "security": AgentConfig(
                    llm=LLMConfig(model="claude-opus-4-6", temperature=0.1)
                )
            }
        )
        effective = config.llm_for_agent("security")
        assert effective.model == "claude-opus-4-6"
        assert effective.temperature == 0.1
        # Falls back to default provider
        assert effective.provider == LLMProvider.NVIDIA

    def test_agent_disabled(self):
        config = AuditConfig(
            agents={"performance": AgentConfig(enabled=False)}
        )
        assert config.is_agent_enabled("performance") is False
        assert config.is_agent_enabled("security") is True  # default enabled

    def test_llm_for_agent_no_override(self):
        config = AuditConfig()
        effective = config.llm_for_agent("security")
        assert effective == config.llm


# ── deep_merge ────────────────────────────────────────────────────────────

class TestDeepMerge:
    def test_basic_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"review": {"mode": "deep", "include": ["**/*"]}}
        override = {"review": {"mode": "quick"}}
        result = deep_merge(base, override)
        assert result["review"]["mode"] == "quick"
        assert result["review"]["include"] == ["**/*"]

    def test_empty_override(self):
        base = {"a": 1}
        assert deep_merge(base, {}) == {"a": 1}

    def test_empty_base(self):
        override = {"a": 1}
        assert deep_merge({}, override) == {"a": 1}

"""Configuration discovery and loading.

Priority (highest first): CLI flags > project config > global config > defaults.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import ValidationError

from code_audit.config.defaults import CONFIG_FILE_NAMES, GLOBAL_CONFIG_DIR, GLOBAL_CONFIG_FILE
from code_audit.config.models import AuditConfig, ReviewMode


def find_project_config(start_path: Path) -> Path | None:
    """Search for a project config file walking up from start_path."""
    current = start_path.resolve()
    while current != current.parent:
        for name in CONFIG_FILE_NAMES:
            candidate = current / name
            if candidate.is_file():
                return candidate
        current = current.parent
    return None


def find_global_config() -> Path | None:
    """Find the global config file."""
    global_dir = Path(GLOBAL_CONFIG_DIR).expanduser()
    config_path = global_dir / GLOBAL_CONFIG_FILE
    if config_path.is_file():
        return config_path
    return None


def load_yaml_or_json(path: Path) -> dict:
    """Load a YAML or JSON file into a dict."""
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".json",):
        return json.loads(text)
    return yaml.safe_load(text) or {}


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Override values take precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(
    project_path: Path | None = None,
    mode: ReviewMode | None = None,
    diff_target: str | None = None,
) -> AuditConfig:
    """Load and merge configuration from all sources.

    Args:
        project_path: Project directory to search for config. Defaults to cwd.
        mode: CLI override for review mode.
        diff_target: CLI override for diff target.

    Returns:
        Fully merged AuditConfig.
    """
    merged: dict = {}

    # 1. Global config (lowest priority)
    global_path = find_global_config()
    if global_path:
        try:
            global_data = load_yaml_or_json(global_path)
            merged = deep_merge(merged, global_data)
        except Exception:
            pass  # Silently skip malformed global config

    # 2. Project config
    search_from = project_path or Path.cwd()
    project_config_path = find_project_config(search_from)
    if project_config_path:
        try:
            project_data = load_yaml_or_json(project_config_path)
            merged = deep_merge(merged, project_data)
        except Exception:
            pass  # Silently skip malformed project config

    # 3. CLI overrides (highest priority)
    if mode is not None:
        merged.setdefault("review", {})["mode"] = mode.value
    if diff_target is not None:
        merged.setdefault("review", {})["diff_target"] = diff_target

    # 4. Parse into validated config
    try:
        config = AuditConfig(**merged)
    except ValidationError:
        # Fall back to defaults if config is malformed
        config = AuditConfig()
        if mode:
            config.review.mode = mode
        if diff_target:
            config.review.diff_target = diff_target

    return config

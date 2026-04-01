"""Tests for the dependency vulnerability scanner."""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from code_audit.scanners.dependencies import DependencyScanner, CVE_SEVERITY_MAP, ECOSYSTEM_FILES
from code_audit.models.finding import Severity


class TestEcosystemDetection:
    def test_detects_npm(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        scanner = DependencyScanner(tmp_path)
        assert "npm" in scanner.detect_ecosystems()

    def test_detects_pip(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==2.0")
        scanner = DependencyScanner(tmp_path)
        assert "pip" in scanner.detect_ecosystems()

    def test_detects_go(self, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/foo")
        scanner = DependencyScanner(tmp_path)
        assert "go" in scanner.detect_ecosystems()

    def test_detects_cargo(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text("[package]")
        scanner = DependencyScanner(tmp_path)
        assert "cargo" in scanner.detect_ecosystems()

    def test_detects_multiple(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "requirements.txt").write_text("")
        scanner = DependencyScanner(tmp_path)
        ecosystems = scanner.detect_ecosystems()
        assert "npm" in ecosystems
        assert "pip" in ecosystems

    def test_no_ecosystems(self, tmp_path):
        scanner = DependencyScanner(tmp_path)
        assert scanner.detect_ecosystems() == []


class TestCveSeverityMapping:
    def test_critical_maps_to_important(self):
        assert CVE_SEVERITY_MAP["critical"] == Severity.IMPORTANT

    def test_high_maps_to_important(self):
        assert CVE_SEVERITY_MAP["high"] == Severity.IMPORTANT

    def test_moderate_maps_to_nit(self):
        assert CVE_SEVERITY_MAP["moderate"] == Severity.NIT

    def test_low_maps_to_pre_existing(self):
        assert CVE_SEVERITY_MAP["low"] == Severity.PRE_EXISTING


class TestNpmParsing:
    @pytest.mark.asyncio
    async def test_parse_npm_audit_output(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        scanner = DependencyScanner(tmp_path)

        mock_output = json.dumps({
            "vulnerabilities": {
                "lodash": {
                    "severity": "high",
                    "via": [{"title": "Prototype Pollution", "url": "https://github.com/advisories/GHSA-1234"}],
                    "range": "<4.17.21",
                }
            }
        })

        with patch.object(scanner, '_run_tool', new_callable=AsyncMock, return_value=(mock_output, 0)):
            findings = await scanner._scan_npm()
            assert len(findings) == 1
            assert findings[0].severity == Severity.IMPORTANT
            assert "lodash" in findings[0].title
            assert findings[0].dimension == "dependencies"

    @pytest.mark.asyncio
    async def test_empty_npm_output(self, tmp_path):
        scanner = DependencyScanner(tmp_path)
        with patch.object(scanner, '_run_tool', new_callable=AsyncMock, return_value=("", 0)):
            findings = await scanner._scan_npm()
            assert findings == []


class TestPipParsing:
    @pytest.mark.asyncio
    async def test_parse_pip_audit_output(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==1.0")
        scanner = DependencyScanner(tmp_path)

        mock_output = json.dumps({
            "dependencies": [{
                "name": "flask",
                "version": "1.0",
                "vulns": [{
                    "id": "CVE-2023-1234",
                    "description": "Security vulnerability in Flask",
                    "fix_versions": ["2.3.3"],
                }]
            }]
        })

        with patch.object(scanner, '_run_tool', new_callable=AsyncMock, return_value=(mock_output, 0)):
            findings = await scanner._scan_pip()
            assert len(findings) == 1
            assert "flask" in findings[0].title
            assert "CVE-2023-1234" in findings[0].tags


class TestToolMissing:
    @pytest.mark.asyncio
    async def test_missing_tool_skipped(self, tmp_path):
        (tmp_path / "package.json").write_text("{}")
        scanner = DependencyScanner(tmp_path)

        with patch.object(scanner, '_run_tool', side_effect=FileNotFoundError("npm not found")):
            findings = await scanner.scan()
            assert findings == []

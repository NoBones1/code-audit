"""Dependency vulnerability scanner (Software Composition Analysis).

Shells out to free tools (npm audit, pip-audit, osv-scanner) to check
for known CVEs in project dependencies. Zero LLM cost.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from code_audit.models.finding import Finding, FindingLocation, Severity

logger = logging.getLogger(__name__)

# Map CVE severity strings to our Severity enum
CVE_SEVERITY_MAP: dict[str, Severity] = {
    "critical": Severity.IMPORTANT,
    "high": Severity.IMPORTANT,
    "moderate": Severity.NIT,
    "medium": Severity.NIT,
    "low": Severity.PRE_EXISTING,
    "info": Severity.PRE_EXISTING,
}

# Map lockfile/manifest to ecosystem
ECOSYSTEM_FILES: dict[str, str] = {
    "package.json": "npm",
    "package-lock.json": "npm",
    "yarn.lock": "npm",
    "requirements.txt": "pip",
    "pyproject.toml": "pip",
    "Pipfile.lock": "pip",
    "go.mod": "go",
    "go.sum": "go",
    "Cargo.toml": "cargo",
    "Cargo.lock": "cargo",
}


class DependencyScanner:
    """Scans project dependencies for known vulnerabilities."""

    def __init__(self, project_path: Path):
        self.project_path = project_path

    def detect_ecosystems(self) -> list[str]:
        """Detect which package ecosystems are present in the project."""
        found: set[str] = set()
        for filename, ecosystem in ECOSYSTEM_FILES.items():
            if (self.project_path / filename).exists():
                found.add(ecosystem)
        return sorted(found)

    async def scan(self) -> list[Finding]:
        """Run vulnerability scans for all detected ecosystems."""
        ecosystems = self.detect_ecosystems()
        if not ecosystems:
            logger.info("No package manifests found, skipping dependency scan")
            return []

        all_findings: list[Finding] = []
        for eco in ecosystems:
            try:
                if eco == "npm":
                    findings = await self._scan_npm()
                elif eco == "pip":
                    findings = await self._scan_pip()
                elif eco == "go":
                    findings = await self._scan_osv()
                elif eco == "cargo":
                    findings = await self._scan_cargo()
                else:
                    continue
                all_findings.extend(findings)
            except FileNotFoundError as e:
                logger.warning(f"Tool not found for {eco}: {e}. Skipping.")
            except Exception as e:
                logger.warning(f"Dependency scan failed for {eco}: {e}")

        return all_findings

    async def _run_tool(self, cmd: list[str], timeout: float = 60.0) -> tuple[str, int]:
        """Run a CLI tool and return (stdout, exit_code)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_path,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return stdout.decode("utf-8", errors="replace"), proc.returncode or 0
        except FileNotFoundError:
            raise FileNotFoundError(f"Command not found: {cmd[0]}")
        except asyncio.TimeoutError:
            logger.warning(f"Command timed out after {timeout}s: {' '.join(cmd)}")
            return "", 1

    async def _scan_npm(self) -> list[Finding]:
        """Run npm audit and parse results."""
        stdout, code = await self._run_tool(["npm", "audit", "--json"])
        if not stdout.strip():
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            logger.warning("Failed to parse npm audit JSON output")
            return []

        findings: list[Finding] = []

        # npm audit v7+ format: data.vulnerabilities is a dict
        vulnerabilities = data.get("vulnerabilities", {})
        for pkg_name, vuln_info in vulnerabilities.items():
            severity_str = vuln_info.get("severity", "moderate")
            severity = CVE_SEVERITY_MAP.get(severity_str, Severity.NIT)

            via_list = vuln_info.get("via", [])
            # via can be strings (transitive) or dicts (direct)
            description_parts = []
            cve_tags = []
            for via in via_list:
                if isinstance(via, dict):
                    title = via.get("title", "")
                    url = via.get("url", "")
                    if title:
                        description_parts.append(title)
                    if url:
                        cve_tags.append(url.split("/")[-1] if "/" in url else url)

            description = (
                "; ".join(description_parts) if description_parts
                else f"Vulnerability in {pkg_name}"
            )
            range_str = vuln_info.get("range", "")

            findings.append(Finding(
                dimension="dependencies",
                severity=severity,
                title=f"Vulnerable dependency: {pkg_name}",
                description=f"{description}. Affected versions: {range_str}",
                location=FindingLocation(
                    file_path="package.json",
                    start_line=1,
                    snippet=f"{pkg_name}: {range_str}",
                ),
                suggestion=f"Run `npm audit fix` or update {pkg_name} to a patched version.",
                confidence=0.95,
                tags=["cve", "sca", f"npm:{pkg_name}"] + cve_tags[:3],
            ))

        return findings

    async def _scan_pip(self) -> list[Finding]:
        """Run pip-audit and parse results."""
        stdout, code = await self._run_tool(["pip-audit", "--format=json", "--desc"])
        if not stdout.strip():
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            logger.warning("Failed to parse pip-audit JSON output")
            return []

        findings: list[Finding] = []
        # pip-audit format: {"dependencies": [...], "fixes": [...]}
        for dep in data.get("dependencies", []):
            vulns = dep.get("vulns", [])
            pkg_name = dep.get("name", "unknown")
            version = dep.get("version", "")

            for vuln in vulns:
                vuln_id = vuln.get("id", "")
                description = vuln.get("description", f"Vulnerability in {pkg_name}")
                fix_versions = vuln.get("fix_versions", [])

                # pip-audit doesn't provide severity in all cases -- default to NIT
                severity = Severity.NIT

                suggestion = (
                    f"Update {pkg_name} to version {', '.join(fix_versions)}."
                    if fix_versions
                    else f"Check for updates to {pkg_name}."
                )

                findings.append(Finding(
                    dimension="dependencies",
                    severity=severity,
                    title=f"Vulnerable dependency: {pkg_name} ({vuln_id})",
                    description=f"{description[:200]}. Current version: {version}",
                    location=FindingLocation(
                        file_path=(
                            "requirements.txt"
                            if (self.project_path / "requirements.txt").exists()
                            else "pyproject.toml"
                        ),
                        start_line=1,
                        snippet=f"{pkg_name}=={version}",
                    ),
                    suggestion=suggestion,
                    confidence=0.95,
                    tags=["cve", "sca", vuln_id, f"pip:{pkg_name}"],
                ))

        return findings

    async def _scan_osv(self) -> list[Finding]:
        """Run osv-scanner as a universal fallback."""
        stdout, code = await self._run_tool(
            ["osv-scanner", "--format=json", str(self.project_path)]
        )
        if not stdout.strip():
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return []

        findings: list[Finding] = []
        for result in data.get("results", []):
            source_path = result.get("source", {}).get("path", "")
            for pkg in result.get("packages", []):
                pkg_info = pkg.get("package", {})
                pkg_name = pkg_info.get("name", "unknown")
                version = pkg_info.get("version", "")

                for vuln in pkg.get("vulnerabilities", []):
                    vuln_id = vuln.get("id", "")
                    summary = vuln.get("summary", f"Vulnerability in {pkg_name}")

                    # Determine severity from database_specific or severity field
                    severity_str = ""
                    for sev in vuln.get("severity", []):
                        if sev.get("type") == "CVSS_V3":
                            score_raw = str(sev.get("score", "0"))
                            score = (
                                float(score_raw.split("/")[0])
                                if "/" in score_raw
                                else 0
                            )
                            if score >= 7.0:
                                severity_str = "high"
                            elif score >= 4.0:
                                severity_str = "medium"
                            else:
                                severity_str = "low"
                    severity = CVE_SEVERITY_MAP.get(severity_str, Severity.NIT)

                    findings.append(Finding(
                        dimension="dependencies",
                        severity=severity,
                        title=f"Vulnerable dependency: {pkg_name} ({vuln_id})",
                        description=f"{summary[:200]}. Version: {version}",
                        location=FindingLocation(
                            file_path=source_path or "go.mod",
                            start_line=1,
                            snippet=f"{pkg_name}@{version}",
                        ),
                        suggestion=(
                            f"Update {pkg_name} to a patched version. "
                            f"See https://osv.dev/vulnerability/{vuln_id}"
                        ),
                        confidence=0.95,
                        tags=["cve", "sca", vuln_id],
                    ))

        return findings

    async def _scan_cargo(self) -> list[Finding]:
        """Run cargo audit and parse results."""
        stdout, code = await self._run_tool(["cargo", "audit", "--json"])
        if not stdout.strip():
            return []

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return []

        findings: list[Finding] = []
        for vuln in data.get("vulnerabilities", {}).get("list", []):
            advisory = vuln.get("advisory", {})
            pkg = vuln.get("package", {})

            severity_str = advisory.get("cvss", "")
            severity = Severity.NIT  # Default
            if isinstance(severity_str, str) and severity_str:
                try:
                    score = (
                        float(severity_str.split("/")[0])
                        if "/" in severity_str
                        else float(severity_str)
                    )
                    if score >= 7.0:
                        severity = Severity.IMPORTANT
                    elif score >= 4.0:
                        severity = Severity.NIT
                    else:
                        severity = Severity.PRE_EXISTING
                except (ValueError, IndexError):
                    pass

            vuln_id = advisory.get("id", "")
            findings.append(Finding(
                dimension="dependencies",
                severity=severity,
                title=f"Vulnerable dependency: {pkg.get('name', 'unknown')} ({vuln_id})",
                description=advisory.get("title", f"Vulnerability in {pkg.get('name', '')}"),
                location=FindingLocation(
                    file_path="Cargo.toml",
                    start_line=1,
                    snippet=f"{pkg.get('name', '')}@{pkg.get('version', '')}",
                ),
                suggestion=advisory.get(
                    "url", f"Update {pkg.get('name', '')} to a patched version."
                ),
                confidence=0.95,
                tags=["cve", "sca", vuln_id],
            ))

        return findings

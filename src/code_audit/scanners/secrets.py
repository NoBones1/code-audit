"""Secrets and credential detection scanner.

Pure regex-based pre-pass that runs before LLM agents.
Zero LLM cost. Catches hardcoded API keys, tokens, passwords, and private keys.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from code_audit.models.finding import Finding, FindingLocation, Severity


@dataclass
class SecretPattern:
    """A regex pattern for detecting a specific type of secret."""
    name: str
    pattern: re.Pattern
    severity: Severity
    description: str


# Allowlist: lines containing these words are likely examples/tests, not real secrets
ALLOWLIST_WORDS = frozenset({
    "example", "placeholder", "test", "dummy", "fake", "todo",
    "sample", "mock", "fixture", "xxx", "changeme", "your-",
    "insert", "replace", "<your", "REPLACE_ME",
})

SECRET_PATTERNS: list[SecretPattern] = [
    # AWS
    SecretPattern("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}"), Severity.IMPORTANT,
                  "AWS Access Key ID detected. This grants access to AWS services."),
    SecretPattern("AWS Secret Key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"), Severity.IMPORTANT,
                  "AWS Secret Access Key detected."),

    # GitHub
    SecretPattern("GitHub PAT", re.compile(r"ghp_[A-Za-z0-9]{36}"), Severity.IMPORTANT,
                  "GitHub Personal Access Token detected."),
    SecretPattern("GitHub PAT (fine-grained)", re.compile(r"github_pat_[A-Za-z0-9_]{82}"), Severity.IMPORTANT,
                  "GitHub fine-grained Personal Access Token detected."),
    SecretPattern("GitHub OAuth", re.compile(r"gho_[A-Za-z0-9]{36}"), Severity.IMPORTANT,
                  "GitHub OAuth Access Token detected."),

    # Slack
    SecretPattern("Slack Token", re.compile(r"xox[bpors]-[A-Za-z0-9\-]{10,}"), Severity.IMPORTANT,
                  "Slack API token detected."),
    SecretPattern("Slack Webhook", re.compile(r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"), Severity.IMPORTANT,
                  "Slack incoming webhook URL detected."),

    # Private Keys
    SecretPattern("Private Key", re.compile(r"-----BEGIN (RSA|EC|DSA|OPENSSH|PGP) PRIVATE KEY-----"), Severity.IMPORTANT,
                  "Private key detected. Never commit private keys to version control."),

    # Generic API Keys
    SecretPattern("OpenAI API Key", re.compile(r"sk-[A-Za-z0-9]{20,}"), Severity.IMPORTANT,
                  "OpenAI-style API key detected (sk-...)."),
    SecretPattern("NVIDIA API Key", re.compile(r"nvapi-[A-Za-z0-9]{20,}"), Severity.IMPORTANT,
                  "NVIDIA API key detected."),
    SecretPattern("Anthropic API Key", re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"), Severity.IMPORTANT,
                  "Anthropic API key detected."),

    # Google
    SecretPattern("Google API Key", re.compile(r"AIza[0-9A-Za-z\-_]{35}"), Severity.IMPORTANT,
                  "Google API key detected."),
    SecretPattern("Google OAuth Client Secret", re.compile(r"GOCSPX-[A-Za-z0-9\-]{28}"), Severity.IMPORTANT,
                  "Google OAuth client secret detected."),

    # Stripe
    SecretPattern("Stripe Secret Key", re.compile(r"sk_live_[A-Za-z0-9]{24,}"), Severity.IMPORTANT,
                  "Stripe live secret key detected."),
    SecretPattern("Stripe Publishable Key", re.compile(r"pk_live_[A-Za-z0-9]{24,}"), Severity.NIT,
                  "Stripe live publishable key detected (public, but verify intent)."),

    # Twilio
    SecretPattern("Twilio API Key", re.compile(r"SK[0-9a-fA-F]{32}"), Severity.IMPORTANT,
                  "Twilio API key detected."),

    # SendGrid
    SecretPattern("SendGrid API Key", re.compile(r"SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}"), Severity.IMPORTANT,
                  "SendGrid API key detected."),

    # Mailgun
    SecretPattern("Mailgun API Key", re.compile(r"key-[A-Za-z0-9]{32}"), Severity.IMPORTANT,
                  "Mailgun API key detected."),

    # Database URLs with credentials
    SecretPattern("Database URL with Password", re.compile(r"(?i)(postgres|mysql|mongodb|redis)://[^:]+:[^@]+@[^\s]+"), Severity.IMPORTANT,
                  "Database connection string with embedded credentials detected."),

    # Generic password assignment
    SecretPattern("Hardcoded Password", re.compile(r"""(?i)(?:password|passwd|pwd|secret)\s*[=:]\s*['"][^'"]{8,}['"]"""), Severity.IMPORTANT,
                  "Hardcoded password or secret detected in source code."),

    # JWT
    SecretPattern("JWT Token", re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), Severity.NIT,
                  "JWT token detected. Verify this is not a production token."),

    # Heroku
    SecretPattern("Heroku API Key", re.compile(r"(?i)heroku.*['\"][0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}['\"]"), Severity.IMPORTANT,
                  "Heroku API key detected."),

    # NPM
    SecretPattern("NPM Token", re.compile(r"npm_[A-Za-z0-9]{36}"), Severity.IMPORTANT,
                  "NPM access token detected."),

    # PyPI
    SecretPattern("PyPI Token", re.compile(r"pypi-[A-Za-z0-9\-_]{50,}"), Severity.IMPORTANT,
                  "PyPI API token detected."),
]


def _shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    length = len(s)
    return -sum((count / length) * math.log2(count / length) for count in freq.values())


def _is_allowlisted(line: str) -> bool:
    """Check if a line is likely an example/test, not a real secret."""
    lower = line.lower()
    return any(word in lower for word in ALLOWLIST_WORDS)


def _redact(value: str, show_chars: int = 6) -> str:
    """Redact a secret value, showing only first few characters."""
    if len(value) <= show_chars:
        return "***"
    return value[:show_chars] + "..." + "*" * min(8, len(value) - show_chars)


class SecretsScanner:
    """Scans source files for hardcoded secrets and credentials."""

    def scan_file(self, file_path: str, content: str) -> list[Finding]:
        """Scan a single file for secrets."""
        findings: list[Finding] = []
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            # Skip empty lines and comments
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue

            # Skip allowlisted lines
            if _is_allowlisted(line):
                continue

            # Check each pattern
            for pattern in SECRET_PATTERNS:
                match = pattern.pattern.search(line)
                if match:
                    matched_text = match.group(0)
                    finding = Finding(
                        dimension="secrets",
                        severity=pattern.severity,
                        title=f"{pattern.name} detected",
                        description=pattern.description,
                        location=FindingLocation(
                            file_path=file_path,
                            start_line=line_num,
                            snippet=line.strip()[:120],  # Truncate long lines
                        ),
                        suggestion=f"Remove the hardcoded secret and use an environment variable instead. Rotate this credential immediately if it was ever committed.",
                        confidence=0.95,
                        tags=["secret-exposure", "cwe-798"],
                    )
                    findings.append(finding)
                    break  # One finding per line (avoid duplicates)

        # High-entropy string detection (only near relevant keywords)
        entropy_findings = self._scan_entropy(file_path, lines)
        findings.extend(entropy_findings)

        return findings

    def _scan_entropy(self, file_path: str, lines: list[str]) -> list[Finding]:
        """Detect high-entropy strings near secret-related keywords."""
        findings: list[Finding] = []
        keyword_re = re.compile(r"(?i)(key|token|secret|password|credential|auth|api_key|apikey|access_key)")
        string_re = re.compile(r"""['"]([A-Za-z0-9+/=\-_]{20,})['"]""")

        for line_num, line in enumerate(lines, start=1):
            if _is_allowlisted(line):
                continue
            if not keyword_re.search(line):
                continue

            for match in string_re.finditer(line):
                value = match.group(1)
                entropy = _shannon_entropy(value)
                if entropy > 4.5 and len(value) >= 20:
                    # Check it's not already caught by a specific pattern
                    already_caught = any(p.pattern.search(line) for p in SECRET_PATTERNS)
                    if not already_caught:
                        findings.append(Finding(
                            dimension="secrets",
                            severity=Severity.NIT,
                            title="High-entropy string near secret keyword",
                            description=f"A high-entropy string (Shannon entropy: {entropy:.1f}) was found near a secret-related keyword. This may be a hardcoded credential.",
                            location=FindingLocation(
                                file_path=file_path,
                                start_line=line_num,
                                snippet=line.strip()[:120],
                            ),
                            suggestion="Verify this is not a hardcoded credential. If it is, move it to an environment variable.",
                            confidence=0.6,
                            tags=["secret-exposure", "high-entropy"],
                        ))

        return findings

    # Paths that contain test fixtures with fake secrets — skip these
    TEST_PATH_PATTERNS = frozenset({
        "test_", "tests/", "__tests__/", "fixtures/", "mock", "spec/",
    })

    def _is_test_file(self, file_path: str) -> bool:
        """Check if a file is a test/fixture file (likely contains fake secrets)."""
        lower = file_path.lower()
        return any(pattern in lower for pattern in self.TEST_PATH_PATTERNS)

    def scan_files(self, files: dict[str, str]) -> list[Finding]:
        """Scan multiple files for secrets."""
        all_findings: list[Finding] = []
        for file_path, content in files.items():
            # Skip binary-looking or very large files
            if len(content) > 500_000:
                continue
            # Skip test files (they contain intentional fake secrets for testing)
            if self._is_test_file(file_path):
                continue
            all_findings.extend(self.scan_file(file_path, content))
        return all_findings

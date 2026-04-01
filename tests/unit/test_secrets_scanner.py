"""Tests for the secrets scanner."""
import pytest
from code_audit.scanners.secrets import SecretsScanner, _shannon_entropy, _is_allowlisted, SECRET_PATTERNS
from code_audit.models.finding import Severity


class TestShannonEntropy:
    def test_empty_string(self):
        assert _shannon_entropy("") == 0.0

    def test_single_char(self):
        assert _shannon_entropy("aaaa") == 0.0

    def test_high_entropy(self):
        # Random-looking string should have high entropy
        assert _shannon_entropy("aB3kL9mN2pQ7rS5t") > 3.5

    def test_low_entropy(self):
        assert _shannon_entropy("aaaaabbbbb") < 1.5


class TestAllowlist:
    def test_example_line(self):
        assert _is_allowlisted('API_KEY = "example-key-here"')

    def test_test_line(self):
        assert _is_allowlisted('test_secret = "sk-test12345"')

    def test_real_line(self):
        assert not _is_allowlisted('API_KEY = "sk-prod-abc123def456"')

    def test_placeholder(self):
        assert _is_allowlisted('TOKEN = "placeholder"')


class TestSecretsScanner:
    def setup_method(self):
        self.scanner = SecretsScanner()

    def test_detects_aws_key(self):
        content = 'aws_key = "AKIAIOSFODNN7PRODKEY1"'
        findings = self.scanner.scan_file("config.py", content)
        assert len(findings) >= 1
        assert findings[0].dimension == "secrets"
        assert findings[0].severity == Severity.IMPORTANT
        assert "AWS" in findings[0].title

    def test_detects_github_pat(self):
        content = 'token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"'
        findings = self.scanner.scan_file("auth.py", content)
        assert len(findings) >= 1
        assert "GitHub" in findings[0].title

    def test_detects_private_key(self):
        content = '-----BEGIN RSA PRIVATE KEY-----'
        findings = self.scanner.scan_file("key.pem", content)
        assert len(findings) >= 1
        assert "Private" in findings[0].title

    def test_detects_openai_key(self):
        content = 'OPENAI_KEY = "sk-abcdefghijklmnopqrstuvwxyz123456"'
        findings = self.scanner.scan_file("config.py", content)
        assert len(findings) >= 1

    def test_detects_nvidia_key(self):
        content = 'key = "nvapi-vjMQeeOoENLOZ5HxHbkqDZcqLA6mJ1VPjaKp"'
        findings = self.scanner.scan_file("config.py", content)
        assert len(findings) >= 1
        assert "NVIDIA" in findings[0].title

    def test_detects_database_url(self):
        content = 'DATABASE_URL = "postgres://admin:p4ssw0rd@db.prod-host.com:5432/mydb"'
        findings = self.scanner.scan_file(".env", content)
        assert len(findings) >= 1

    def test_detects_hardcoded_password(self):
        content = 'password = "super_secret_password_123"'
        findings = self.scanner.scan_file("config.py", content)
        assert len(findings) >= 1
        assert "password" in findings[0].title.lower() or "Password" in findings[0].title

    def test_skips_example_values(self):
        content = 'API_KEY = "example-key-replace-me"'
        findings = self.scanner.scan_file("config.py", content)
        assert len(findings) == 0

    def test_skips_test_values(self):
        content = 'test_token = "ghp_TESTABCDEFGHIJKLMNOPQRSTUVWXYZtest12"'
        findings = self.scanner.scan_file("test_auth.py", content)
        assert len(findings) == 0

    def test_skips_comments(self):
        content = '# API_KEY = "AKIAIOSFODNN7EXAMPLE"'
        findings = self.scanner.scan_file("config.py", content)
        assert len(findings) == 0

    def test_scan_multiple_files(self):
        files = {
            "config.py": 'API_KEY = "AKIAIOSFODNN7PRODKEY1"',
            "clean.py": 'print("hello")',
            "auth.py": 'token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"',
        }
        findings = self.scanner.scan_files(files)
        assert len(findings) >= 2

    def test_empty_file(self):
        findings = self.scanner.scan_file("empty.py", "")
        assert len(findings) == 0

    def test_high_entropy_near_keyword(self):
        content = 'api_key = "aB3kL9mN2pQ7rS5tUv8WxYz1234567890ab"'
        findings = self.scanner.scan_file("config.py", content)
        # Should catch either via pattern or entropy
        assert len(findings) >= 1

    def test_finding_has_correct_fields(self):
        content = 'key = "AKIAIOSFODNN7PRODKEY1"'
        findings = self.scanner.scan_file("app.py", content)
        assert len(findings) >= 1
        f = findings[0]
        assert f.dimension == "secrets"
        assert f.location.file_path == "app.py"
        assert f.location.start_line == 1
        assert f.confidence > 0
        assert len(f.tags) > 0
        assert "cwe-798" in f.tags

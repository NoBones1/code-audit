"""Unit tests for diff parsing — parse_hunks, parse_diff, _validate_diff_target, _filter_diffs."""

import pytest
from unittest.mock import MagicMock

from code_audit.context.diff import (
    parse_hunks,
    parse_diff,
    _validate_diff_target,
    detect_language,
    is_lockfile,
    is_binary_extension,
)
from code_audit.models.context import FileDiff


# ── parse_hunks ───────────────────────────────────────────────────────────

class TestParseHunks:
    def test_single_hunk(self):
        text = (
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            "-old line\n"
            "+new line\n"
            "+added line\n"
            " line3"
        )
        hunks = parse_hunks(text)
        assert len(hunks) == 1
        assert hunks[0].old_start == 1
        assert hunks[0].old_count == 3
        assert hunks[0].new_start == 1
        assert hunks[0].new_count == 4
        assert "+new line" in hunks[0].content
        assert "-old line" in hunks[0].content

    def test_multiple_hunks(self):
        text = (
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "-old1\n"
            "+new1\n"
            "@@ -10,4 +10,5 @@ def func():\n"
            " context2\n"
            "+added2\n"
            " more"
        )
        hunks = parse_hunks(text)
        assert len(hunks) == 2
        assert hunks[0].old_start == 1
        assert hunks[0].new_start == 1
        assert hunks[1].old_start == 10
        assert hunks[1].new_start == 10
        assert hunks[1].old_count == 4
        assert hunks[1].new_count == 5

    def test_empty_input(self):
        assert parse_hunks("") == []

    def test_no_hunk_headers(self):
        assert parse_hunks("just some random text\nno hunks here") == []

    def test_hunk_with_no_count_defaults_to_one(self):
        """When hunk header omits the count (e.g. @@ -5 +5 @@) it defaults to 1."""
        text = "@@ -5 +5 @@\n+single line"
        hunks = parse_hunks(text)
        assert len(hunks) == 1
        assert hunks[0].old_count == 1
        assert hunks[0].new_count == 1


# ── parse_diff (parse_git_diff equivalent) ────────────────────────────────

class TestParseDiff:
    SINGLE_FILE_DIFF = (
        "diff --git a/app.py b/app.py\n"
        "index abc123..def456 100644\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,3 +1,4 @@\n"
        " import os\n"
        "-old_func()\n"
        "+new_func()\n"
        "+added_func()\n"
        " end\n"
    )

    def test_single_file_diff(self):
        files = parse_diff(self.SINGLE_FILE_DIFF)
        assert len(files) == 1
        assert files[0].file_path == "app.py"
        assert files[0].status == "modified"
        assert files[0].language == "Python"
        assert files[0].additions == 2
        assert files[0].deletions == 1
        assert len(files[0].hunks) == 1

    def test_multiple_files(self):
        diff = (
            "diff --git a/app.py b/app.py\n"
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/main.js b/main.js\n"
            "--- a/main.js\n"
            "+++ b/main.js\n"
            "@@ -5,3 +5,4 @@\n"
            " ctx\n"
            "+added\n"
            " end\n"
        )
        files = parse_diff(diff)
        assert len(files) == 2
        assert files[0].file_path == "app.py"
        assert files[1].file_path == "main.js"
        assert files[1].language == "JavaScript"

    def test_binary_file(self):
        diff = (
            "diff --git a/logo.png b/logo.png\n"
            "Binary files a/logo.png and b/logo.png differ\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].is_binary is True
        assert files[0].file_path == "logo.png"

    def test_binary_by_extension(self):
        """Files with binary extensions are detected even without Binary marker."""
        diff = (
            "diff --git a/icon.ico b/icon.ico\n"
            "--- a/icon.ico\n"
            "+++ b/icon.ico\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].is_binary is True

    def test_new_file(self):
        diff = (
            "diff --git a/new.py b/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+line1\n"
            "+line2\n"
            "+line3\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].status == "added"

    def test_deleted_file(self):
        diff = (
            "diff --git a/old.py b/old.py\n"
            "deleted file mode 100644\n"
            "--- a/old.py\n"
            "+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n"
            "-line1\n"
            "-line2\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].status == "deleted"

    def test_rename(self):
        diff = (
            "diff --git a/old_name.py b/new_name.py\n"
            "similarity index 90%\n"
            "rename from old_name.py\n"
            "rename to new_name.py\n"
            "--- a/old_name.py\n"
            "+++ b/new_name.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-old\n"
            "+new\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert files[0].status == "renamed"
        assert files[0].file_path == "new_name.py"
        assert files[0].old_path == "old_name.py"

    def test_lockfile_truncation(self):
        diff = (
            "diff --git a/package-lock.json b/package-lock.json\n"
            "--- a/package-lock.json\n"
            "+++ b/package-lock.json\n"
            "@@ -1,5 +1,8 @@\n"
            " {\n"
            '+  "new-dep": "1.0.0",\n'
            '+  "another": "2.0.0",\n'
            '+  "third": "3.0.0",\n'
            " }\n"
        )
        files = parse_diff(diff)
        assert len(files) == 1
        assert len(files[0].hunks) == 1
        assert "truncated" in files[0].hunks[0].content.lower()

    def test_empty_diff(self):
        assert parse_diff("") == []
        assert parse_diff("   \n  ") == []


# ── _validate_diff_target ─────────────────────────────────────────────────

class TestValidateDiffTarget:
    @pytest.mark.parametrize("ref", [
        "HEAD",
        "main",
        "abc1234",
        "feature/branch-name",
        "HEAD~3",
        "v1.0.0",
        "origin/main",
        "HEAD^",
    ])
    def test_valid_refs(self, ref):
        # Should not raise
        _validate_diff_target(ref)

    @pytest.mark.parametrize("ref", [
        "--exec=cmd",
        "-flag",
        "--option",
    ])
    def test_rejects_flags(self, ref):
        with pytest.raises(ValueError, match="cannot start with '-'"):
            _validate_diff_target(ref)

    @pytest.mark.parametrize("ref", [
        "ref with spaces",
        "ref;injection",
        "ref$(cmd)",
        "ref`cmd`",
        "ref|pipe",
    ])
    def test_rejects_special_chars(self, ref):
        with pytest.raises(ValueError, match="disallowed characters"):
            _validate_diff_target(ref)


# ── _filter_diffs (tested via Orchestrator) ───────────────────────────────

class TestFilterDiffs:
    """Test the _filter_diffs method from Orchestrator with mocked config."""

    def _make_orchestrator(self, include=None, exclude=None):
        """Create an Orchestrator-like object with _filter_diffs method inlined."""
        from code_audit.config.models import AuditConfig, ReviewConfig

        config = AuditConfig(
            review=ReviewConfig(
                include=include or ["**/*"],
                exclude=exclude or [],
            )
        )

        # Import the actual method — it lives on Orchestrator, so we import the class
        # and create an instance with minimal setup.
        from code_audit.engine.orchestrator import Orchestrator
        orch = object.__new__(Orchestrator)
        orch.config = config
        return orch

    def _make_diff(self, path):
        return FileDiff(file_path=path, status="modified")

    def test_default_include_all(self):
        orch = self._make_orchestrator()
        diffs = [self._make_diff("src/app.py"), self._make_diff("lib/util.js")]
        result = orch._filter_diffs(diffs)
        assert len(result) == 2

    def test_exclude_node_modules(self):
        orch = self._make_orchestrator(exclude=["node_modules/**"])
        diffs = [
            self._make_diff("src/app.py"),
            self._make_diff("node_modules/pkg/index.js"),
        ]
        result = orch._filter_diffs(diffs)
        assert len(result) == 1
        assert result[0].file_path == "src/app.py"

    def test_exclude_test_files_double_star(self):
        orch = self._make_orchestrator(exclude=["**/*.test.*"])
        diffs = [
            self._make_diff("src/app.py"),
            self._make_diff("src/app.test.py"),
            self._make_diff("tests/app.test.js"),
        ]
        result = orch._filter_diffs(diffs)
        assert len(result) == 1
        assert result[0].file_path == "src/app.py"

    def test_include_src_prefix(self):
        orch = self._make_orchestrator(include=["src/**"])
        diffs = [
            self._make_diff("src/app.py"),
            self._make_diff("src/lib/util.py"),
            self._make_diff("docs/readme.md"),
        ]
        result = orch._filter_diffs(diffs)
        assert len(result) == 2
        assert all(d.file_path.startswith("src/") for d in result)

    def test_include_py_suffix(self):
        orch = self._make_orchestrator(include=["**/*.py"])
        diffs = [
            self._make_diff("src/app.py"),
            self._make_diff("main.js"),
            self._make_diff("lib/util.py"),
        ]
        result = orch._filter_diffs(diffs)
        assert len(result) == 2
        assert all(d.file_path.endswith(".py") for d in result)

    def test_exclude_lockfiles(self):
        orch = self._make_orchestrator(exclude=["*.lock", "package-lock.json"])
        diffs = [
            self._make_diff("src/app.py"),
            self._make_diff("poetry.lock"),
            self._make_diff("package-lock.json"),
        ]
        result = orch._filter_diffs(diffs)
        assert len(result) == 1
        assert result[0].file_path == "src/app.py"


# ── Helper functions ──────────────────────────────────────────────────────

class TestHelpers:
    def test_detect_language(self):
        assert detect_language("app.py") == "Python"
        assert detect_language("main.js") == "JavaScript"
        assert detect_language("lib.rs") == "Rust"
        assert detect_language("unknown.xyz") is None

    def test_is_lockfile(self):
        assert is_lockfile("package-lock.json") is True
        assert is_lockfile("yarn.lock") is True
        assert is_lockfile("Gemfile.lock") is True
        assert is_lockfile("app.py") is False

    def test_is_binary_extension(self):
        assert is_binary_extension("logo.png") is True
        assert is_binary_extension("font.woff2") is True
        assert is_binary_extension("app.py") is False

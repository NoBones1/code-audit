"""Output generation -- terminal, markdown, and SARIF."""

from code_audit.output.terminal import TerminalOutput
from code_audit.output.markdown import render_markdown_report
from code_audit.output.sarif_writer import write_sarif

__all__ = ["TerminalOutput", "render_markdown_report", "write_sarif"]

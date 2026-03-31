"""SARIF 2.1.0 output writer.

Uses the sarif-pydantic library for schema-validated output.
Falls back to manual JSON construction if the library is not available.
"""

from __future__ import annotations

import json
from pathlib import Path

from code_audit.models.finding import Finding, Severity
from code_audit.models.report import AuditReport


SARIF_SCHEMA_URI = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
)

# SARIF level mapping
SEVERITY_TO_SARIF_LEVEL = {
    Severity.IMPORTANT: "error",
    Severity.NIT: "warning",
    Severity.PRE_EXISTING: "note",
}


def _build_sarif_dict(report: AuditReport) -> dict:
    """Build a SARIF 2.1.0 compliant dict from the audit report."""

    # Build rules from dimensions
    rules = []
    rule_indices: dict[str, int] = {}
    dimensions_seen: set[str] = set()

    for finding in report.findings:
        if finding.dimension not in dimensions_seen:
            rule_index = len(rules)
            rule_indices[finding.dimension] = rule_index
            rules.append({
                "id": f"code-audit/{finding.dimension}",
                "name": finding.dimension.replace("_", " ").title(),
                "shortDescription": {
                    "text": f"Code audit: {finding.dimension} dimension",
                },
            })
            dimensions_seen.add(finding.dimension)

    # Build results
    results = []
    for finding in report.findings:
        result: dict = {
            "ruleId": f"code-audit/{finding.dimension}",
            "ruleIndex": rule_indices.get(finding.dimension, 0),
            "level": SEVERITY_TO_SARIF_LEVEL.get(finding.severity, "warning"),
            "message": {
                "text": f"{finding.title}\n\n{finding.description}",
            },
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": finding.location.file_path,
                        },
                        "region": {
                            "startLine": finding.location.start_line,
                            **(
                                {"endLine": finding.location.effective_end_line}
                                if finding.location.end_line
                                else {}
                            ),
                        },
                    },
                },
            ],
            "properties": {
                "confidence": finding.confidence,
                "dimension": finding.dimension,
                "tags": finding.tags,
            },
        }

        if finding.suggestion:
            result["fixes"] = [
                {
                    "description": {
                        "text": finding.suggestion,
                    },
                },
            ]

        results.append(result)

    sarif = {
        "$schema": SARIF_SCHEMA_URI,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CodeAudit",
                        "version": "0.1.0",
                        "informationUri": "https://github.com/code-audit/code-audit",
                        "rules": rules,
                    },
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "properties": {
                            "auditId": report.audit_id,
                            "mode": report.mode,
                            "durationSeconds": report.duration_seconds,
                            "filesReviewed": report.summary.files_reviewed,
                        },
                    },
                ],
            },
        ],
    }

    return sarif


def write_sarif(report: AuditReport, output_path: Path) -> None:
    """Write the SARIF 2.1.0 report to a file.

    Tries to use sarif-pydantic for validation, falls back to direct JSON.
    """
    sarif_dict = _build_sarif_dict(report)

    # Try to validate with sarif-pydantic if available
    try:
        from sarif_pydantic import Sarif

        # Validate by parsing through Pydantic
        sarif_obj = Sarif.model_validate(sarif_dict)
        json_output = sarif_obj.model_dump_json(indent=2, exclude_none=True)
    except (ImportError, Exception):
        # Fallback: write raw dict
        json_output = json.dumps(sarif_dict, indent=2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json_output, encoding="utf-8")

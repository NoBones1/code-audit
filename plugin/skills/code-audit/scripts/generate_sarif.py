#!/usr/bin/env python3
"""Generate SARIF 2.1.0 JSON from a CodeAudit markdown report.

Reads .audit/report.md, parses findings, and writes .audit/results.sarif.

Usage:
    python3 generate_sarif.py [--input .audit/report.md] [--output .audit/results.sarif]

This script can be called by the CodeAudit plugin to produce machine-readable output.
It has zero dependencies beyond the Python standard library.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SARIF_SCHEMA = (
    "https://docs.oasis-open.org/sarif/sarif/v2.1.0/errata01/os/schemas/sarif-schema-2.1.0.json"
)

SEVERITY_TO_LEVEL = {
    "important": "error",
    "nit": "warning",
    "pre_existing": "note",
    "pre-existing": "note",
}

# Regex patterns for parsing the markdown report
FINDING_TITLE_RE = re.compile(r"^\*\*(.+?)\*\*\s*—?\s*`(.+?)`")
LOCATION_RE = re.compile(r"`([^`]+?):(\d+)(?:-(\d+))?`")
SEVERITY_SECTION_RE = re.compile(r"^###\s*(🔴|🟡|🟣)\s*(Important|Nit|Pre-existing)", re.IGNORECASE)
CONFIDENCE_RE = re.compile(r"\*\*Confidence\*\*:\s*(\d+)%")
DIMENSION_RE = re.compile(r"\*\*Dimension\*\*:\s*(\w+)")
TAGS_RE = re.compile(r"\*\*Tags\*\*:\s*(.+)")


def parse_findings_from_json(json_path: Path) -> list[dict]:
    """Try to parse findings from .audit/report.json if it exists."""
    if not json_path.is_file():
        return []
    try:
        data = json.loads(json_path.read_text())
        return data.get("findings", [])
    except (json.JSONDecodeError, KeyError):
        return []


def findings_to_sarif(findings: list[dict]) -> dict:
    """Convert a list of finding dicts to SARIF 2.1.0."""
    rules = {}
    results = []

    for finding in findings:
        dimension = finding.get("dimension", "combined")
        rule_id = f"code-audit/{dimension}"

        if rule_id not in rules:
            rules[rule_id] = {
                "id": rule_id,
                "name": dimension.replace("_", " ").title(),
                "shortDescription": {"text": f"Code audit: {dimension} dimension"},
            }

        severity = finding.get("severity", "nit")
        level = SEVERITY_TO_LEVEL.get(severity, "warning")

        title = finding.get("title", "Untitled finding")
        description = finding.get("description", "")
        file_path = finding.get("file_path", finding.get("location", {}).get("file_path", "unknown"))
        start_line = finding.get("start_line", finding.get("location", {}).get("start_line", 1))
        confidence = finding.get("confidence", 0.5)

        result = {
            "ruleId": rule_id,
            "level": level,
            "message": {"text": f"{title}\n\n{description}"},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": file_path},
                        "region": {"startLine": int(start_line)},
                    }
                }
            ],
            "properties": {
                "confidence": confidence,
                "dimension": dimension,
                "tags": finding.get("tags", []),
            },
        }

        suggestion = finding.get("suggestion")
        if suggestion:
            result["fixes"] = [{"description": {"text": suggestion}}]

        results.append(result)

    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CodeAudit",
                        "version": "0.1.0",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Generate SARIF from CodeAudit report")
    parser.add_argument("--input", default=".audit/report.json", help="Path to report.json")
    parser.add_argument("--output", default=".audit/results.sarif", help="Output SARIF path")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    findings = parse_findings_from_json(input_path)
    if not findings:
        print(f"No findings found in {input_path}", file=sys.stderr)
        # Write empty SARIF
        sarif = findings_to_sarif([])
    else:
        sarif = findings_to_sarif(findings)
        print(f"Generated SARIF with {len(findings)} findings")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(sarif, indent=2))
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()

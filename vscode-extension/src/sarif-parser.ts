/**
 * SARIF 2.1.0 parser — reads .audit/results.sarif into finding objects.
 */

import * as fs from "fs";

export interface SarifFinding {
  ruleId: string;
  level: string; // "error" | "warning" | "note"
  message: string;
  filePath: string;
  startLine: number;
  endLine: number | null;
  dimension: string;
  confidence: number;
  tags: string[];
  suggestion: string | null;
}

export async function parseSarifFindings(
  sarifPath: string
): Promise<SarifFinding[]> {
  const content = fs.readFileSync(sarifPath, "utf-8");
  const sarif = JSON.parse(content);

  if (sarif.version !== "2.1.0") {
    throw new Error(`Unsupported SARIF version: ${sarif.version}`);
  }

  const findings: SarifFinding[] = [];

  for (const run of sarif.runs || []) {
    for (const result of run.results || []) {
      const location = result.locations?.[0]?.physicalLocation;
      const filePath = location?.artifactLocation?.uri || "unknown";
      const startLine = location?.region?.startLine || 1;
      const endLine = location?.region?.endLine || null;

      const properties = result.properties || {};
      const messageText = result.message?.text || "";

      // Extract suggestion from fixes
      let suggestion: string | null = null;
      if (result.fixes?.length > 0) {
        suggestion = result.fixes[0].description?.text || null;
      }

      findings.push({
        ruleId: result.ruleId || "unknown",
        level: result.level || "warning",
        message: messageText,
        filePath,
        startLine,
        endLine,
        dimension: properties.dimension || "unknown",
        confidence: properties.confidence || 0.5,
        tags: properties.tags || [],
        suggestion,
      });
    }
  }

  // Sort: errors first, then warnings, then notes
  const levelOrder: Record<string, number> = {
    error: 0,
    warning: 1,
    note: 2,
  };
  findings.sort(
    (a, b) =>
      (levelOrder[a.level] ?? 3) - (levelOrder[b.level] ?? 3)
  );

  return findings;
}

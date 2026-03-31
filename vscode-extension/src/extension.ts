import * as vscode from "vscode";
import { FindingsProvider, FindingItem } from "./findings-provider";
import { HistoryProvider } from "./history-provider";
import { runReview, ReviewMode } from "./runner";
import { parseSarifFindings, SarifFinding } from "./sarif-parser";

let diagnosticCollection: vscode.DiagnosticCollection;
let findingsProvider: FindingsProvider;
let historyProvider: HistoryProvider;
let statusBarItem: vscode.StatusBarItem;
let currentFindings: SarifFinding[] = [];

export function activate(context: vscode.ExtensionContext) {
  // Diagnostic collection for inline squiggly lines
  diagnosticCollection = vscode.languages.createDiagnosticCollection("codeAudit");
  context.subscriptions.push(diagnosticCollection);

  // Tree view providers
  findingsProvider = new FindingsProvider();
  historyProvider = new HistoryProvider();
  vscode.window.registerTreeDataProvider("codeAuditFindings", findingsProvider);
  vscode.window.registerTreeDataProvider("codeAuditHistory", historyProvider);

  // Status bar item
  statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    100
  );
  statusBarItem.command = "codeAudit.reviewQuick";
  statusBarItem.text = "$(shield) CodeAudit";
  statusBarItem.tooltip = "Click to run a quick code review";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand("codeAudit.reviewQuick", () =>
      executeReview("quick", context)
    ),
    vscode.commands.registerCommand("codeAudit.reviewDeep", () =>
      executeReview("deep", context)
    ),
    vscode.commands.registerCommand("codeAudit.reviewSecurity", () =>
      executeReview("security", context)
    ),
    vscode.commands.registerCommand(
      "codeAudit.dismissFinding",
      (item: FindingItem) => dismissFinding(item)
    ),
    vscode.commands.registerCommand("codeAudit.openReport", () =>
      openReport()
    )
  );

  // Load existing findings from .audit/results.sarif if present
  loadExistingFindings();
}

async function executeReview(
  mode: ReviewMode,
  context: vscode.ExtensionContext
) {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) {
    vscode.window.showErrorMessage(
      "CodeAudit: No workspace folder open"
    );
    return;
  }

  const config = vscode.workspace.getConfiguration("codeAudit");
  const cliPath = config.get<string>("pythonPath", "code-audit");
  const diffTarget = config.get<string>("diffTarget", "HEAD");

  // Update status bar
  statusBarItem.text = "$(loading~spin) CodeAudit: reviewing...";
  statusBarItem.tooltip = `Running ${mode} review...`;

  try {
    const sarifPath = await runReview(
      cliPath,
      workspaceFolder.uri.fsPath,
      mode,
      diffTarget
    );

    // Parse SARIF and update UI
    const findings = await parseSarifFindings(sarifPath);
    currentFindings = findings;

    // Update diagnostics (squiggly lines)
    updateDiagnostics(findings, workspaceFolder.uri.fsPath);

    // Update sidebar tree
    findingsProvider.setFindings(findings);

    // Update history
    historyProvider.refresh();

    // Update status bar
    const importantCount = findings.filter(
      (f) => f.level === "error"
    ).length;
    const totalCount = findings.length;

    if (totalCount === 0) {
      statusBarItem.text = "$(check) CodeAudit: clean";
      statusBarItem.tooltip = "No issues found";
      vscode.window.showInformationMessage(
        "CodeAudit: No issues found!"
      );
    } else {
      statusBarItem.text = `$(warning) CodeAudit: ${totalCount} findings`;
      statusBarItem.tooltip = `${importantCount} important, ${totalCount - importantCount} other`;
      vscode.window.showWarningMessage(
        `CodeAudit: Found ${totalCount} issues (${importantCount} important)`
      );
    }
  } catch (error: any) {
    statusBarItem.text = "$(error) CodeAudit: failed";
    statusBarItem.tooltip = error.message;
    vscode.window.showErrorMessage(
      `CodeAudit review failed: ${error.message}`
    );
  }
}

function updateDiagnostics(
  findings: SarifFinding[],
  workspacePath: string
) {
  diagnosticCollection.clear();

  // Group findings by file
  const byFile = new Map<string, SarifFinding[]>();
  for (const finding of findings) {
    const filePath = finding.filePath;
    if (!byFile.has(filePath)) {
      byFile.set(filePath, []);
    }
    byFile.get(filePath)!.push(finding);
  }

  // Create diagnostics per file
  for (const [filePath, fileFindings] of byFile) {
    const uri = vscode.Uri.file(`${workspacePath}/${filePath}`);
    const diagnostics: vscode.Diagnostic[] = [];

    for (const finding of fileFindings) {
      const startLine = Math.max(0, finding.startLine - 1); // VS Code is 0-indexed
      const endLine = finding.endLine
        ? Math.max(0, finding.endLine - 1)
        : startLine;

      const range = new vscode.Range(startLine, 0, endLine, 1000);

      const severity = mapSeverity(finding.level);
      const diagnostic = new vscode.Diagnostic(
        range,
        finding.message,
        severity
      );
      diagnostic.source = "CodeAudit";
      diagnostic.code = finding.ruleId;

      // Add related information if there's a suggestion
      if (finding.suggestion) {
        diagnostic.message += `\n\nSuggestion: ${finding.suggestion}`;
      }

      diagnostics.push(diagnostic);
    }

    diagnosticCollection.set(uri, diagnostics);
  }
}

function mapSeverity(
  level: string
): vscode.DiagnosticSeverity {
  switch (level) {
    case "error":
      return vscode.DiagnosticSeverity.Error;
    case "warning":
      return vscode.DiagnosticSeverity.Warning;
    case "note":
      return vscode.DiagnosticSeverity.Information;
    default:
      return vscode.DiagnosticSeverity.Warning;
  }
}

async function dismissFinding(item: FindingItem) {
  const reason = await vscode.window.showInputBox({
    prompt: "Why are you dismissing this finding? (optional)",
    placeHolder: "e.g., intentional pattern, false positive, not applicable",
  });

  if (reason === undefined) {
    return; // User cancelled
  }

  // Record the dismissal via the CLI
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) return;

  const config = vscode.workspace.getConfiguration("codeAudit");
  const cliPath = config.get<string>("pythonPath", "code-audit");

  // Write dismissal to memory via the Python CLI
  // For now, write directly to the memory file
  const memoryDir = `${workspaceFolder.uri.fsPath}/.code-audit/memory`;
  const decisionsPath = `${memoryDir}/decisions.json`;

  try {
    const fs = require("fs");
    fs.mkdirSync(memoryDir, { recursive: true });

    let decisions: any[] = [];
    if (fs.existsSync(decisionsPath)) {
      decisions = JSON.parse(fs.readFileSync(decisionsPath, "utf-8"));
    }

    decisions.push({
      finding_title: item.finding.message.split("\n")[0],
      finding_dimension: item.finding.dimension || "unknown",
      finding_tags: [],
      file_pattern: item.finding.filePath,
      action: "dismissed",
      reason: reason || "",
      timestamp: new Date().toISOString(),
      audit_id: "",
    });

    fs.writeFileSync(decisionsPath, JSON.stringify(decisions, null, 2));

    // Remove from current findings
    currentFindings = currentFindings.filter((f) => f !== item.finding);
    findingsProvider.setFindings(currentFindings);

    // Refresh diagnostics
    if (workspaceFolder) {
      updateDiagnostics(currentFindings, workspaceFolder.uri.fsPath);
    }

    vscode.window.showInformationMessage(
      `Finding dismissed: ${item.finding.message.split("\n")[0].substring(0, 60)}...`
    );
  } catch (error: any) {
    vscode.window.showErrorMessage(
      `Failed to dismiss finding: ${error.message}`
    );
  }
}

async function openReport() {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) return;

  const reportPath = vscode.Uri.file(
    `${workspaceFolder.uri.fsPath}/.audit/report.md`
  );

  try {
    await vscode.workspace.openTextDocument(reportPath);
    await vscode.window.showTextDocument(
      await vscode.workspace.openTextDocument(reportPath),
      { preview: true }
    );
  } catch {
    vscode.window.showErrorMessage(
      "CodeAudit: No report found. Run a review first."
    );
  }
}

async function loadExistingFindings() {
  const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
  if (!workspaceFolder) return;

  const sarifPath = `${workspaceFolder.uri.fsPath}/.audit/results.sarif`;
  try {
    const findings = await parseSarifFindings(sarifPath);
    if (findings.length > 0) {
      currentFindings = findings;
      updateDiagnostics(findings, workspaceFolder.uri.fsPath);
      findingsProvider.setFindings(findings);
      statusBarItem.text = `$(warning) CodeAudit: ${findings.length} findings`;
    }
  } catch {
    // No existing findings — that's fine
  }
}

export function deactivate() {
  diagnosticCollection?.dispose();
  statusBarItem?.dispose();
}

/**
 * Tree view provider for the findings sidebar panel.
 *
 * Groups findings by severity, then by file.
 */

import * as vscode from "vscode";
import { SarifFinding } from "./sarif-parser";

const SEVERITY_ICONS: Record<string, string> = {
  error: "🔴",
  warning: "🟡",
  note: "🟣",
};

const SEVERITY_LABELS: Record<string, string> = {
  error: "Important",
  warning: "Nit",
  note: "Pre-existing",
};

export class FindingItem extends vscode.TreeItem {
  constructor(
    public readonly finding: SarifFinding,
    public readonly collapsibleState: vscode.TreeItemCollapsibleState
  ) {
    const icon = SEVERITY_ICONS[finding.level] || "⚪";
    const title = finding.message.split("\n")[0].substring(0, 80);
    super(`${icon} ${title}`, collapsibleState);

    this.tooltip = finding.message;
    this.description = finding.filePath + ":" + finding.startLine;

    // Click to navigate to the file
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (workspaceFolder) {
      const uri = vscode.Uri.file(
        `${workspaceFolder.uri.fsPath}/${finding.filePath}`
      );
      this.command = {
        title: "Go to finding",
        command: "vscode.open",
        arguments: [
          uri,
          {
            selection: new vscode.Range(
              Math.max(0, finding.startLine - 1),
              0,
              Math.max(0, finding.startLine - 1),
              0
            ),
          },
        ],
      };
    }

    // Context menu for dismiss action
    this.contextValue = "finding";
  }
}

class SeverityGroupItem extends vscode.TreeItem {
  constructor(
    public readonly level: string,
    public readonly findings: SarifFinding[],
    public readonly collapsibleState: vscode.TreeItemCollapsibleState
  ) {
    const icon = SEVERITY_ICONS[level] || "⚪";
    const label = SEVERITY_LABELS[level] || level;
    super(`${icon} ${label} (${findings.length})`, collapsibleState);
  }
}

export class FindingsProvider
  implements vscode.TreeDataProvider<vscode.TreeItem>
{
  private _onDidChangeTreeData = new vscode.EventEmitter<
    vscode.TreeItem | undefined
  >();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private findings: SarifFinding[] = [];

  setFindings(findings: SarifFinding[]) {
    this.findings = findings;
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: vscode.TreeItem): vscode.TreeItem[] {
    if (!element) {
      // Root level: group by severity
      const groups: Record<string, SarifFinding[]> = {};
      for (const f of this.findings) {
        if (!groups[f.level]) groups[f.level] = [];
        groups[f.level].push(f);
      }

      const order = ["error", "warning", "note"];
      return order
        .filter((level) => groups[level]?.length > 0)
        .map(
          (level) =>
            new SeverityGroupItem(
              level,
              groups[level],
              vscode.TreeItemCollapsibleState.Expanded
            )
        );
    }

    if (element instanceof SeverityGroupItem) {
      return element.findings.map(
        (f) =>
          new FindingItem(f, vscode.TreeItemCollapsibleState.None)
      );
    }

    return [];
  }
}

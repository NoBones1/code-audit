/**
 * Tree view provider for the audit history sidebar panel.
 *
 * Shows past audit runs with their summary stats.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";

interface AuditRecord {
  audit_id: string;
  timestamp: string;
  mode: string;
  files_reviewed: number;
  total_findings: number;
  important: number;
  nit: number;
  pre_existing: number;
  duration_seconds: number;
}

export class HistoryProvider
  implements vscode.TreeDataProvider<vscode.TreeItem>
{
  private _onDidChangeTreeData = new vscode.EventEmitter<
    vscode.TreeItem | undefined
  >();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  refresh() {
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(): vscode.TreeItem[] {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) return [];

    const historyPath = path.join(
      workspaceFolder.uri.fsPath,
      ".code-audit",
      "memory",
      "audit_history.json"
    );

    if (!fs.existsSync(historyPath)) {
      return [
        new vscode.TreeItem(
          "No audit history yet",
          vscode.TreeItemCollapsibleState.None
        ),
      ];
    }

    try {
      const data: AuditRecord[] = JSON.parse(
        fs.readFileSync(historyPath, "utf-8")
      );

      // Show most recent first, limit to 20
      return data
        .slice(-20)
        .reverse()
        .map((record) => {
          const date = new Date(record.timestamp);
          const dateStr = date.toLocaleDateString("en-GB", {
            day: "2-digit",
            month: "short",
            hour: "2-digit",
            minute: "2-digit",
          });

          const icon =
            record.important > 0
              ? "🔴"
              : record.total_findings > 0
              ? "🟡"
              : "✅";

          const item = new vscode.TreeItem(
            `${icon} ${dateStr} — ${record.total_findings} findings (${record.mode})`,
            vscode.TreeItemCollapsibleState.None
          );
          item.tooltip = [
            `Audit: ${record.audit_id}`,
            `Mode: ${record.mode}`,
            `Files: ${record.files_reviewed}`,
            `Important: ${record.important}`,
            `Nit: ${record.nit}`,
            `Pre-existing: ${record.pre_existing}`,
            `Duration: ${record.duration_seconds.toFixed(0)}s`,
          ].join("\n");
          item.description = `${record.files_reviewed} files, ${record.duration_seconds.toFixed(0)}s`;

          return item;
        });
    } catch {
      return [
        new vscode.TreeItem(
          "Error reading history",
          vscode.TreeItemCollapsibleState.None
        ),
      ];
    }
  }
}

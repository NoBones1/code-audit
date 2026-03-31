/**
 * CLI runner — invokes the code-audit CLI and returns the SARIF path.
 */

import { exec } from "child_process";
import * as path from "path";

export type ReviewMode = "quick" | "deep" | "security";

export function runReview(
  cliPath: string,
  workspacePath: string,
  mode: ReviewMode,
  diffTarget: string
): Promise<string> {
  return new Promise((resolve, reject) => {
    const sarifPath = path.join(workspacePath, ".audit", "results.sarif");

    const cmd = `${cliPath} review --mode ${mode} --diff-target ${diffTarget} --path "${workspacePath}"`;

    const childProcess = exec(cmd, {
      cwd: workspacePath,
      timeout: 30 * 60 * 1000, // 30 minute timeout for deep reviews
      env: {
        ...process.env,
        // Ensure the venv Python is on the path
        PATH: process.env.PATH,
      },
    });

    let stdout = "";
    let stderr = "";

    childProcess.stdout?.on("data", (data) => {
      stdout += data;
    });

    childProcess.stderr?.on("data", (data) => {
      stderr += data;
    });

    childProcess.on("close", (code) => {
      if (code === 0) {
        resolve(sarifPath);
      } else {
        reject(
          new Error(
            `code-audit exited with code ${code}: ${stderr || stdout}`
          )
        );
      }
    });

    childProcess.on("error", (error) => {
      reject(new Error(`Failed to start code-audit: ${error.message}`));
    });
  });
}

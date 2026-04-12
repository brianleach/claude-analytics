/**
 * Generate the HTML dashboard from parsed data.
 */

import * as fs from "fs";
import * as path from "path";

import type { ParsedData } from "./parser";
import type { RecommendationResult } from "./analyzer";

// ============================================================
// Template loading
// ============================================================

function getTemplate(): string {
  // Look for template.html relative to this file (works both in src/ and dist/)
  const candidates = [
    path.join(__dirname, "..", "template.html"),
    path.join(__dirname, "..", "..", "template.html"),
    path.join(process.cwd(), "template.html"),
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) {
      return fs.readFileSync(p, "utf-8");
    }
  }
  throw new Error(
    `Template not found. Searched: ${candidates.join(", ")}`
  );
}

// ============================================================
// HTML generation
// ============================================================

export function generateHtml(
  data: ParsedData,
  recommendations: RecommendationResult
): string {
  const template = getTemplate();

  const payload: Record<string, unknown> = {
    dashboard: data.dashboard,
    drilldown: data.drilldown,
    analysis: data.analysis,
    recommendations,
    work_days: data.work_days || [],
    models: data.models || [],
    subagents: data.subagents || {},
    branches: data.branches || [],
    context_efficiency: data.context_efficiency || {},
    versions: data.versions || [],
    skills: data.skills || [],
    slash_commands: data.slash_commands || [],
    config: data.config || {},
  };

  const payloadJson = JSON.stringify(payload);
  const html = template.replace("__DATA_PLACEHOLDER__", payloadJson);
  return html;
}

// ============================================================
// Report writing
// ============================================================

export function writeReport(html: string, outputPath?: string | null): string {
  let finalPath: string;

  if (!outputPath) {
    const outputDir = path.join(process.cwd(), "output");
    fs.mkdirSync(outputDir, { recursive: true });

    const now = new Date();
    const timestamp = [
      now.getFullYear(),
      String(now.getMonth() + 1).padStart(2, "0"),
      String(now.getDate()).padStart(2, "0"),
      "-",
      String(now.getHours()).padStart(2, "0"),
      String(now.getMinutes()).padStart(2, "0"),
      String(now.getSeconds()).padStart(2, "0"),
    ].join("");
    finalPath = path.join(outputDir, `claude-analytics-${timestamp}.html`);

    ensureGitignore(outputDir);
  } else {
    finalPath = outputPath;
  }

  const dir = path.dirname(finalPath);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(finalPath, html, "utf-8");

  return finalPath;
}

// ============================================================
// Last-run tracking
// ============================================================

export function readLastRun(outputDir?: string): string | null {
  const dir = outputDir || path.join(process.cwd(), "output");
  const marker = path.join(dir, ".last-run");
  if (fs.existsSync(marker)) {
    const content = fs.readFileSync(marker, "utf-8").trim();
    return content.length >= 10 ? content.substring(0, 10) : null;
  }
  return null;
}

export function saveLastRun(outputDir?: string): void {
  const dir = outputDir || path.join(process.cwd(), "output");
  fs.mkdirSync(dir, { recursive: true });
  const marker = path.join(dir, ".last-run");
  const now = new Date();
  const ts = [
    now.getFullYear(),
    "-",
    String(now.getMonth() + 1).padStart(2, "0"),
    "-",
    String(now.getDate()).padStart(2, "0"),
    " ",
    String(now.getHours()).padStart(2, "0"),
    ":",
    String(now.getMinutes()).padStart(2, "0"),
    ":",
    String(now.getSeconds()).padStart(2, "0"),
  ].join("");
  fs.writeFileSync(marker, ts + "\n", "utf-8");
}

// ============================================================
// Gitignore management
// ============================================================

function ensureGitignore(outputDir: string): void {
  const innerGitignore = path.join(outputDir, ".gitignore");
  if (!fs.existsSync(innerGitignore)) {
    fs.writeFileSync(
      innerGitignore,
      "# Claude Analytics reports contain sensitive session data.\n" +
        "# Do NOT commit these files to version control.\n" +
        "*\n" +
        "!.gitignore\n",
      "utf-8"
    );
  }

  const rootGitignore = path.join(path.dirname(outputDir), ".gitignore");
  if (fs.existsSync(rootGitignore)) {
    const content = fs.readFileSync(rootGitignore, "utf-8");
    if (!content.includes("output/")) {
      fs.appendFileSync(
        rootGitignore,
        "\n# Claude Analytics reports (contain sensitive data)\noutput/\n",
        "utf-8"
      );
    }
  } else {
    fs.writeFileSync(
      rootGitignore,
      "# Claude Analytics reports (contain sensitive data)\noutput/\n",
      "utf-8"
    );
  }
}

#!/usr/bin/env node

/**
 * CLI entry point for claude-analytics (TypeScript port).
 */

import * as fs from "fs";
import * as path from "path";
import * as os from "os";
import { exec } from "child_process";

import { findClaudeDir, parseAllSessions } from "./parser";
import { generateRecommendations } from "./analyzer";
import { generateHtml, writeReport, readLastRun, saveLastRun } from "./generator";

// ============================================================
// Constants
// ============================================================

const VERSION = "0.1.0";

const BANNER_LINES = [
  "   ____ _                 _",
  "  / ___| | __ _ _   _  __| | ___",
  " | |   | |/ _` | | | |/ _` |/ _ \\",
  " | |___| | (_| | |_| | (_| |  __/",
  "  \\____|_|\\__,_|\\__,_|\\__,_|\\___|",
  "     _                _       _   _",
  "    / \\   _ __   __ _| |_   _| |_(_) ___ ___",
  "   / _ \\ | '_ \\ / _` | | | | | __| |/ __/ __|",
  "  / ___ \\| | | | (_| | | |_| | |_| | (__\\__ \\",
  " /_/   \\_\\_| |_|\\__,_|_|\\__, |\\__|_|\\___|___/",
  "                         |___/",
];

const ORANGE = "\x1b[38;2;227;115;34m";
const RESET = "\x1b[0m";
const BANNER =
  "\n" + BANNER_LINES.map((line) => `${ORANGE}${line}${RESET}`).join("\n") + "\n";

// ============================================================
// Argument parsing (no external deps)
// ============================================================

interface CliArgs {
  noApi: boolean;
  noOpen: boolean;
  output: string | null;
  claudeDir: string | null;
  tzOffset: number | null;
  since: string | null;
  version: boolean;
  help: boolean;
}

function parseArgs(argv: string[]): CliArgs {
  const args: CliArgs = {
    noApi: false,
    noOpen: false,
    output: null,
    claudeDir: null,
    tzOffset: null,
    since: null,
    version: false,
    help: false,
  };

  let i = 0;
  while (i < argv.length) {
    const arg = argv[i];
    switch (arg) {
      case "--no-api":
        args.noApi = true;
        break;
      case "--no-open":
        args.noOpen = true;
        break;
      case "-o":
      case "--output":
        i++;
        args.output = argv[i] || null;
        break;
      case "--claude-dir":
        i++;
        args.claudeDir = argv[i] || null;
        break;
      case "--tz-offset":
        i++;
        args.tzOffset = argv[i] != null ? parseInt(argv[i], 10) : null;
        break;
      case "--since":
        i++;
        args.since = argv[i] || null;
        break;
      case "--version":
      case "-v":
        args.version = true;
        break;
      case "--help":
      case "-h":
        args.help = true;
        break;
      default:
        // If it looks like --key=value, handle that
        if (arg.startsWith("--") && arg.includes("=")) {
          const [key, val] = arg.split("=", 2);
          switch (key) {
            case "--output":
              args.output = val;
              break;
            case "--claude-dir":
              args.claudeDir = val;
              break;
            case "--tz-offset":
              args.tzOffset = parseInt(val, 10);
              break;
            case "--since":
              args.since = val;
              break;
          }
        }
        break;
    }
    i++;
  }

  return args;
}

function printHelp(): void {
  console.log(`claude-analytics v${VERSION}

Analyze your Claude Code usage and level up your prompting.

Usage: claude-analytics [options]

Options:
  --no-api          Skip AI-powered analysis (no API key needed)
  --no-open         Don't auto-open the report in the browser
  -o, --output      Output path for the HTML report
  --claude-dir      Path to .claude directory (default: ~/.claude)
  --tz-offset       Timezone offset from UTC in hours (auto-detected)
  --since           Only include data since this date (YYYY-MM-DD) or 'last'
  --version, -v     Show version
  --help, -h        Show this help
`);
}

// ============================================================
// .env loader
// ============================================================

function loadEnv(): void {
  // Load .env from project root (two levels up from ports/typescript/)
  const projectRoot = path.resolve(__dirname, "..", "..", "..");
  const envPath = path.join(projectRoot, ".env");
  if (!fs.existsSync(envPath)) return;
  const content = fs.readFileSync(envPath, "utf-8");
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const eqIdx = trimmed.indexOf("=");
    const key = trimmed.substring(0, eqIdx).trim();
    let val = trimmed.substring(eqIdx + 1).trim();
    // Strip surrounding quotes
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.substring(1, val.length - 1);
    }
    if (key && !(key in process.env)) {
      process.env[key] = val;
    }
  }
}

// ============================================================
// Browser opener
// ============================================================

function openInBrowser(filepath: string): void {
  const platform = os.platform();
  let cmd: string;
  if (platform === "darwin") {
    cmd = `open "${filepath}"`;
  } else if (platform === "win32") {
    cmd = `start "" "${filepath}"`;
  } else {
    cmd = `xdg-open "${filepath}"`;
  }
  exec(cmd, (err) => {
    if (err) {
      // Fallback: just print the URL
      console.log(`  Open manually: file://${filepath}`);
    }
  });
}

// ============================================================
// Main
// ============================================================

async function main(): Promise<void> {
  loadEnv();

  const args = parseArgs(process.argv.slice(2));

  if (args.version) {
    console.log(`claude-analytics ${VERSION}`);
    process.exit(0);
  }

  if (args.help) {
    printHelp();
    process.exit(0);
  }

  console.log(BANNER);
  console.log(`  v${VERSION}`);
  console.log();

  // Step 1: Find Claude directory
  console.log(`${ORANGE}[1/5]${RESET} Locating Claude data...`);
  let claudeDir: string;
  try {
    if (args.claudeDir) {
      if (!fs.existsSync(args.claudeDir)) {
        console.log(`  Error: ${args.claudeDir} not found`);
        process.exit(1);
      }
      claudeDir = args.claudeDir;
    } else {
      claudeDir = findClaudeDir();
    }
    console.log(`  Found: ${claudeDir}`);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    console.log(`  Error: ${msg}`);
    process.exit(1);
  }

  // Resolve --since flag
  let sinceDate: string | null = null;
  if (args.since) {
    if (args.since.toLowerCase() === "last") {
      sinceDate = readLastRun() || null;
      if (sinceDate) {
        console.log(`  Filtering to data since last run: ${sinceDate}`);
      } else {
        console.log("  No previous run found, showing all data");
      }
    } else {
      sinceDate = args.since;
      console.log(`  Filtering to data since: ${sinceDate}`);
    }
  }

  // Step 2: Parse sessions
  console.log(`${ORANGE}[2/5]${RESET} Parsing sessions...`);
  let data;
  try {
    data = parseAllSessions(claudeDir, args.tzOffset, sinceDate);
    const summary = data.dashboard.summary;
    console.log(
      `  ${summary.total_sessions} sessions across ${summary.unique_projects} projects`
    );
    console.log(
      `  ${summary.total_user_msgs.toLocaleString()} messages, ${data.analysis.total_prompts.toLocaleString()} prompts`
    );
    if (sinceDate) {
      console.log(`  Showing: ${sinceDate} → ${summary.date_range_end}`);
    } else {
      console.log(`  ${summary.date_range_start} → ${summary.date_range_end}`);
    }
    console.log(`  Timezone: ${summary.tz_label}`);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    console.log(`  Error: ${msg}`);
    process.exit(1);
  }

  // Step 3: Heuristic analysis
  console.log(`${ORANGE}[3/5]${RESET} Analyzing prompt patterns...`);
  let useApi = !args.noApi;
  if (useApi && !process.env.ANTHROPIC_API_KEY) {
    console.log("  ANTHROPIC_API_KEY not set, using heuristic analysis only");
    console.log("  (set the key or use --no-api to skip this message)");
    useApi = false;
  }

  // Step 4: Generate recommendations
  if (useApi) {
    console.log(`${ORANGE}[4/5]${RESET} Generating AI-powered recommendations (Claude Opus)...`);
  } else {
    console.log(`${ORANGE}[4/5]${RESET} Generating heuristic recommendations...`);
  }
  const recommendations = await generateRecommendations(data, useApi);
  const recCount = recommendations.recommendations.length;
  const sourceLabel = recommendations.source === "ai" ? "AI + heuristic" : "heuristic";
  console.log(`  ${recCount} recommendations (${sourceLabel})`);

  // Step 5: Generate report
  console.log(`${ORANGE}[5/5]${RESET} Generating report...`);
  const html = generateHtml(data, recommendations);
  const outputPath = writeReport(html, args.output);
  console.log(`  Report saved to: ${outputPath}`);

  const fileSize = fs.statSync(outputPath).size;
  const fileSizeKb = Math.round(fileSize / 1024);
  console.log(`  Size: ${fileSizeKb} KB`);

  // Save the last-run marker for --since last
  saveLastRun();
  console.log();

  // Open in browser
  if (!args.noOpen) {
    console.log("Opening report in browser...");
    openInBrowser(outputPath);
  } else {
    console.log(`Open the report: file://${outputPath}`);
  }

  console.log();
  console.log("Done! Go level up your Claude game.");
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});

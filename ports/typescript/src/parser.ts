/**
 * Parse Claude Code session data from ~/.claude/ directory.
 */

import * as fs from "fs";
import * as path from "path";
import * as os from "os";

// ============================================================
// Interfaces
// ============================================================

export interface ModelCost {
  input: number;
  output: number;
  cache_read: number;
  cache_write: number;
}

export interface PromptEntry {
  text: string;
  full_length: number;
  project: string;
  session_id: string;
  date: string;
  time: string;
  hour: number;
  weekday: number;
  category: string;
  length_bucket: string;
}

export interface DrilldownEntry {
  time: string;
  text: string;
  category: string;
  length: number;
  date?: string;
}

export interface SessionMeta {
  project: string;
  session_id: string;
  first_ts: string;
  last_ts: string;
  user_msgs: number;
  assistant_msgs: number;
  tool_uses: number;
  model: string | null;
  entrypoint: string | null;
  msg_count: number;
  git_branch: string | null;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
}

export interface MessageEntry {
  timestamp: string;
  date: string;
  time?: string;
  hour: number;
  weekday: number;
  weekday_name?: string;
  month?: string;
  type: string;
  project: string;
  session_id: string;
  tool_uses?: string[];
  input_tokens?: number;
  output_tokens?: number;
  model?: string;
}

export interface DailyEntry {
  date: string;
  user_msgs: number;
  assistant_msgs: number;
  tool_calls: number;
  output_tokens: number;
  total_msgs: number;
}

export interface HeatmapEntry {
  weekday: number;
  hour: number;
  count: number;
}

export interface ProjectEntry {
  project: string;
  user_msgs: number;
  assistant_msgs: number;
  tool_calls: number;
  sessions: number;
  output_tokens: number;
  total_msgs: number;
}

export interface ToolEntry {
  tool: string;
  count: number;
}

export interface HourlyEntry {
  hour: number;
  count: number;
}

export interface SessionDuration {
  session_id: string;
  project: string;
  duration_min: number;
  user_msgs: number;
  assistant_msgs: number;
  tool_uses: number;
  date: string;
  start_hour: number;
  msgs_per_min: number;
  git_branch: string;
}

export interface WeeklyEntry {
  week: string;
  user_msgs: number;
  sessions: number;
}

export interface EfficiencyEntry {
  hour: number;
  avg_msgs_per_session: number;
  avg_duration: number;
  sessions: number;
}

export interface WorkDay {
  date: string;
  first: string;
  last: string;
  span_hrs: number;
  active_hrs: number;
  prompts: number;
}

export interface CategoryEntry {
  cat: string;
  count: number;
  pct: number;
}

export interface LengthBucketEntry {
  bucket: string;
  count: number;
  pct: number;
}

export interface ProjectQuality {
  project: string;
  count: number;
  avg_len: number;
  confirm_pct: number;
  detailed_pct: number;
  top_cat: string;
}

export interface Analysis {
  total_prompts: number;
  avg_length: number;
  categories: CategoryEntry[];
  length_buckets: LengthBucketEntry[];
  project_quality: ProjectQuality[];
}

export interface ModelBreakdown {
  model: string;
  display: string;
  msgs: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  estimated_cost: number;
}

export interface SubagentEntry {
  agent_id: string;
  type: string;
  description: string;
  is_compaction: boolean;
  project: string;
  messages: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  models: string[];
  duration_min: number;
}

export interface SubagentData {
  subagents: SubagentEntry[];
  type_counts: Record<string, number>;
  total_count: number;
  compaction_count: number;
  total_subagent_input_tokens: number;
  total_subagent_output_tokens: number;
  model_tokens: Record<string, { input: number; output: number; cache_read: number }>;
  estimated_cost: number;
}

export interface BranchEntry {
  branch: string;
  msgs: number;
  sessions: number;
  projects: string[];
}

export interface ContextEfficiency {
  tool_output_tokens: number;
  conversation_tokens: number;
  tool_pct: number;
  conversation_pct: number;
  thinking_blocks: number;
  subagent_output_tokens: number;
  subagent_pct: number;
}

export interface VersionEntry {
  version: string;
  count: number;
}

export interface SkillEntry {
  skill: string;
  count: number;
}

export interface SlashCommandEntry {
  command: string;
  count: number;
}

export interface Config {
  has_config: boolean;
  plugins: string[];
  feature_flags: { name: string; enabled: boolean }[];
  version_info: Record<string, string>;
}

export interface DashboardSummary {
  total_sessions: number;
  total_user_msgs: number;
  total_assistant_msgs: number;
  total_tool_calls: number;
  total_output_tokens: number;
  total_input_tokens: number;
  total_cache_read_tokens: number;
  total_cache_write_tokens: number;
  date_range_start: string;
  date_range_end: string;
  since_date: string;
  unique_projects: number;
  unique_tools: number;
  avg_session_duration: number;
  tz_offset: number;
  tz_label: string;
  estimated_cost: number;
  skipped_files: number;
  skipped_lines: number;
}

export interface Dashboard {
  summary: DashboardSummary;
  daily: DailyEntry[];
  heatmap: HeatmapEntry[];
  projects: ProjectEntry[];
  tools: ToolEntry[];
  hourly: HourlyEntry[];
  sessions: SessionDuration[];
  weekly: WeeklyEntry[];
  efficiency: EfficiencyEntry[];
}

export interface ParsedData {
  dashboard: Dashboard;
  drilldown: Record<string, Record<string, DrilldownEntry[]>>;
  analysis: Analysis;
  prompts: PromptEntry[];
  work_days: WorkDay[];
  models: ModelBreakdown[];
  subagents: SubagentData;
  branches: BranchEntry[];
  context_efficiency: ContextEfficiency;
  versions: VersionEntry[];
  skills: SkillEntry[];
  slash_commands: SlashCommandEntry[];
  permission_modes: Record<string, number>;
  config: Config;
}

// ============================================================
// Cost estimates (per million tokens, USD)
// ============================================================

const MODEL_COSTS: Record<string, ModelCost> = {
  "claude-opus-4": { input: 15.0, output: 75.0, cache_read: 1.5, cache_write: 18.75 },
  "claude-sonnet-4": { input: 3.0, output: 15.0, cache_read: 0.30, cache_write: 3.75 },
  "claude-haiku-4": { input: 0.80, output: 4.0, cache_read: 0.08, cache_write: 1.0 },
};

// ============================================================
// Utility functions
// ============================================================

export function matchModelCost(modelStr: string): ModelCost {
  const m = (modelStr || "").toLowerCase();
  if (m.includes("opus")) return MODEL_COSTS["claude-opus-4"];
  if (m.includes("sonnet")) return MODEL_COSTS["claude-sonnet-4"];
  if (m.includes("haiku")) return MODEL_COSTS["claude-haiku-4"];
  return MODEL_COSTS["claude-sonnet-4"];
}

export function detectTimezoneOffset(): number {
  return new Date().getTimezoneOffset() / -60;
}

export function findClaudeDir(): string {
  const claudeDir = path.join(os.homedir(), ".claude");
  if (!fs.existsSync(claudeDir)) {
    throw new Error(
      `Claude directory not found at ${claudeDir}\n` +
      "Make sure you have Claude Code installed and have used it at least once."
    );
  }
  return claudeDir;
}

function findSessionFiles(claudeDir: string): string[] {
  const projectsDir = path.join(claudeDir, "projects");
  if (!fs.existsSync(projectsDir)) {
    throw new Error(`No projects directory found at ${projectsDir}`);
  }
  const results: string[] = [];
  const projectDirs = fs.readdirSync(projectsDir);
  for (const dir of projectDirs) {
    const dirPath = path.join(projectsDir, dir);
    if (!fs.statSync(dirPath).isDirectory()) continue;
    const files = fs.readdirSync(dirPath);
    for (const file of files) {
      if (file.endsWith(".jsonl") && !file.includes("subagent")) {
        results.push(path.join(dirPath, file));
      }
    }
  }
  return results;
}

function findSubagentFiles(claudeDir: string): { jsonlFiles: string[]; metaFiles: string[] } {
  const projectsDir = path.join(claudeDir, "projects");
  if (!fs.existsSync(projectsDir)) {
    return { jsonlFiles: [], metaFiles: [] };
  }
  const jsonlFiles: string[] = [];
  const metaFiles: string[] = [];

  const projectDirs = fs.readdirSync(projectsDir);
  for (const dir of projectDirs) {
    const dirPath = path.join(projectsDir, dir);
    if (!fs.statSync(dirPath).isDirectory()) continue;
    const sessionDirs = fs.readdirSync(dirPath);
    for (const sdir of sessionDirs) {
      const sdirPath = path.join(dirPath, sdir);
      if (!fs.statSync(sdirPath).isDirectory()) continue;
      const subagentsDir = path.join(sdirPath, "subagents");
      if (!fs.existsSync(subagentsDir) || !fs.statSync(subagentsDir).isDirectory()) continue;
      const files = fs.readdirSync(subagentsDir);
      for (const file of files) {
        const fullPath = path.join(subagentsDir, file);
        if (file.endsWith(".jsonl")) jsonlFiles.push(fullPath);
        if (file.endsWith(".meta.json")) metaFiles.push(fullPath);
      }
    }
  }
  return { jsonlFiles, metaFiles };
}

export function cleanProjectName(dirname: string): string {
  let name = dirname;
  let home = os.homedir().replace(/\//g, "-").replace(/\\/g, "-");
  if (home.startsWith("-")) home = home.substring(1);
  name = name.replace(home + "-", "").replace(home, "home");
  if (name.startsWith("-")) name = name.substring(1);
  return name || "unknown";
}

export function normalizeModelName(modelStr: string): string {
  if (!modelStr) return "unknown";
  const m = modelStr.toLowerCase();
  if (m.includes("opus")) return "Opus";
  if (m.includes("sonnet")) return "Sonnet";
  if (m.includes("haiku")) return "Haiku";
  return modelStr;
}

function hasWord(words: string[], text: string): boolean {
  return words.some((w) => {
    const escaped = w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp("\\b" + escaped + "\\b").test(text);
  });
}

export function categorizePrompt(text: string): string {
  const t = text.toLowerCase().trim();
  if (t.length < 5) return "micro";

  if (
    /^(y(es)?|yeah|yep|ok(ay)?|sure|go|do it|proceed|looks good|lgtm|correct|right|confirm|approved|continue|k|yea|np|go ahead|ship it|perfect|great|nice|good|cool|thanks|ty|thx)\s*$/.test(
      t
    )
  ) {
    return "confirmation";
  }

  if (
    hasWord(
      [
        "error", "bug", "fix", "broken", "crash", "fail", "issue",
        "wrong", "not working", "doesn't work", "won't", "undefined",
        "null", "exception", "traceback",
      ],
      t
    )
  ) {
    return "debugging";
  }

  if (
    hasWord(
      [
        "add", "create", "build", "implement", "make", "new feature",
        "set up", "setup", "write", "generate",
      ],
      t
    )
  ) {
    return "building";
  }

  if (
    hasWord(
      [
        "refactor", "clean up", "rename", "move", "restructure",
        "reorganize", "simplify", "extract",
      ],
      t
    )
  ) {
    return "refactoring";
  }

  const questionStarts = [
    "how", "what", "why", "where", "when", "can you", "is there",
    "do we", "does", "which", "should",
  ];
  if (questionStarts.some((s) => t.startsWith(s))) {
    return "question";
  }

  if (
    hasWord(
      [
        "review", "check", "look at", "examine", "inspect", "analyze",
        "show me", "read", "list", "find",
      ],
      t
    )
  ) {
    return "review";
  }

  if (
    hasWord(
      [
        "update", "change", "modify", "edit", "replace", "remove",
        "delete", "tweak", "adjust",
      ],
      t
    )
  ) {
    return "editing";
  }

  if (hasWord(["test", "spec", "coverage", "assert", "expect"], t)) {
    return "testing";
  }

  if (
    hasWord(
      [
        "commit", "push", "deploy", "merge", "branch", "pr ",
        "pull request", "git ",
      ],
      t
    )
  ) {
    return "git_ops";
  }

  if (t.length < 30) return "brief";
  return "detailed";
}

export function lengthBucket(length: number): string {
  if (length < 20) return "micro (<20)";
  if (length < 50) return "short (20-50)";
  if (length < 150) return "medium (50-150)";
  if (length < 500) return "detailed (150-500)";
  return "comprehensive (500+)";
}

// ============================================================
// Date helpers
// ============================================================

function parseISOTimestamp(ts: string): Date {
  return new Date(ts.replace("Z", "+00:00"));
}

function applyTzOffset(d: Date, tzOffset: number): Date {
  const utcMs = d.getTime();
  return new Date(utcMs + tzOffset * 3600000);
}

function formatDate(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatTime(d: Date): string {
  const h = String(d.getUTCHours()).padStart(2, "0");
  const m = String(d.getUTCMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}

function formatMonth(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function getWeekday(d: Date): number {
  // Python: Monday=0 ... Sunday=6
  const jsDay = d.getUTCDay(); // Sunday=0 ... Saturday=6
  return jsDay === 0 ? 6 : jsDay - 1;
}

function getWeekdayName(d: Date): string {
  const names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  return names[getWeekday(d)];
}

function getISOWeek(d: Date): string {
  // ISO week number
  const dt = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  dt.setUTCDate(dt.getUTCDate() + 3 - ((dt.getUTCDay() + 6) % 7));
  const yearStart = new Date(Date.UTC(dt.getUTCFullYear(), 0, 1));
  const weekNo = Math.ceil(((dt.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return `${dt.getUTCFullYear()}-W${String(weekNo).padStart(2, "0")}`;
}

// ============================================================
// Config parsing
// ============================================================

export function parseConfig(claudeDir: string): Config {
  const configPath = path.join(claudeDir, ".claude.json");
  const config: Config = {
    has_config: false,
    plugins: [],
    feature_flags: [],
    version_info: {},
  };

  if (!fs.existsSync(configPath)) return config;

  try {
    const data = JSON.parse(fs.readFileSync(configPath, "utf-8"));
    config.has_config = true;

    const features = data.cachedGrowthBookFeatures || {};
    const amberLattice = features.tengu_amber_lattice;
    if (amberLattice && typeof amberLattice === "object") {
      const plugins = amberLattice.value;
      if (Array.isArray(plugins)) {
        config.plugins = plugins.filter((p: unknown) => typeof p === "string");
      }
    }

    const flagNames: { name: string; enabled: boolean }[] = [];
    for (const [key, val] of Object.entries(features)) {
      if (val && typeof val === "object" && !Array.isArray(val)) {
        flagNames.push({
          name: key.replace("tengu_", ""),
          enabled: Boolean((val as Record<string, unknown>).value),
        });
      } else if (typeof val === "boolean") {
        flagNames.push({ name: key.replace("tengu_", ""), enabled: val });
      }
    }
    config.feature_flags = flagNames;

    config.version_info = {
      migration_version: data.migrationVersion || "",
      first_start: data.firstStartTime || "",
    };
  } catch {
    // ignore parse errors
  }

  return config;
}

// ============================================================
// Subagent parsing
// ============================================================

export function parseSubagents(claudeDir: string, tzOffset: number): SubagentData {
  const { jsonlFiles, metaFiles } = findSubagentFiles(claudeDir);

  const metaLookup: Record<string, { type: string; description: string }> = {};
  for (const mf of metaFiles) {
    try {
      const meta = JSON.parse(fs.readFileSync(mf, "utf-8"));
      const agentId = path.basename(mf).replace("agent-", "").replace(".meta.json", "");
      metaLookup[agentId] = {
        type: meta.agentType || "unknown",
        description: meta.description || "",
      };
    } catch {
      continue;
    }
  }

  const subagents: SubagentEntry[] = [];
  const typeCounts: Record<string, number> = {};
  const modelTokens: Record<string, { input: number; output: number; cache_read: number }> = {};

  for (const filepath of jsonlFiles) {
    const agentId = path.basename(filepath, ".jsonl").replace("agent-", "");
    const isCompaction = agentId.toLowerCase().includes("compact");
    const meta = metaLookup[agentId] || { type: "unknown", description: "" };
    const agentType = meta.type;
    typeCounts[agentType] = (typeCounts[agentType] || 0) + 1;

    let msgCount = 0;
    let toolCalls = 0;
    let inputTokens = 0;
    let outputTokens = 0;
    let cacheRead = 0;
    const modelsUsed = new Set<string>();
    let firstTs: string | null = null;
    let lastTs: string | null = null;

    try {
      const content = fs.readFileSync(filepath, "utf-8");
      const lines = content.split("\n");
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        let d: Record<string, unknown>;
        try {
          d = JSON.parse(trimmed);
        } catch {
          continue;
        }

        const ts = d.timestamp as string | undefined;
        if (ts) {
          if (!firstTs || ts < firstTs) firstTs = ts;
          if (!lastTs || ts > lastTs) lastTs = ts;
        }

        const msg = d.message as Record<string, unknown> | undefined;
        if (msg && typeof msg === "object") {
          const m = msg.model as string | undefined;
          if (m) modelsUsed.add(m);
          const usage = msg.usage as Record<string, number> | undefined;
          if (usage) {
            inputTokens += usage.input_tokens || 0;
            outputTokens += usage.output_tokens || 0;
            cacheRead += usage.cache_read_input_tokens || 0;
          }
          const msgContent = msg.content;
          if (Array.isArray(msgContent)) {
            for (const c of msgContent) {
              if (c && typeof c === "object" && (c as Record<string, unknown>).type === "tool_use") {
                toolCalls++;
              }
            }
          }
        }
        msgCount++;
      }
    } catch {
      continue;
    }

    // Get parent project
    const parentSessionDir = path.basename(path.dirname(path.dirname(path.dirname(filepath))));
    const projName = cleanProjectName(parentSessionDir);

    let duration = 0;
    if (firstTs && lastTs) {
      try {
        const t1 = parseISOTimestamp(firstTs);
        const t2 = parseISOTimestamp(lastTs);
        duration = (t2.getTime() - t1.getTime()) / 60000;
      } catch {
        // ignore
      }
    }

    subagents.push({
      agent_id: agentId.substring(0, 12),
      type: agentType,
      description: meta.description.substring(0, 80),
      is_compaction: isCompaction,
      project: projName,
      messages: msgCount,
      tool_calls: toolCalls,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      cache_read_tokens: cacheRead,
      models: Array.from(modelsUsed),
      duration_min: Math.round(duration * 10) / 10,
    });

    for (const m of modelsUsed) {
      if (!modelTokens[m]) modelTokens[m] = { input: 0, output: 0, cache_read: 0 };
      const divisor = Math.max(modelsUsed.size, 1);
      modelTokens[m].input += Math.floor(inputTokens / divisor);
      modelTokens[m].output += Math.floor(outputTokens / divisor);
      modelTokens[m].cache_read += Math.floor(cacheRead / divisor);
    }
  }

  return {
    subagents,
    type_counts: typeCounts,
    total_count: subagents.length,
    compaction_count: subagents.filter((s) => s.is_compaction).length,
    total_subagent_input_tokens: subagents.reduce((s, a) => s + a.input_tokens, 0),
    total_subagent_output_tokens: subagents.reduce((s, a) => s + a.output_tokens, 0),
    model_tokens: modelTokens,
    estimated_cost: 0,
  };
}

// ============================================================
// Main parser
// ============================================================

export function parseAllSessions(
  claudeDir: string,
  tzOffset?: number | null,
  sinceDate?: string | null
): ParsedData {
  if (tzOffset == null) {
    tzOffset = detectTimezoneOffset();
  }

  const sessionFiles = findSessionFiles(claudeDir);
  if (sessionFiles.length === 0) {
    throw new Error("No session files found. Use Claude Code for a while first!");
  }

  // === Pass 1: Extract all messages ===
  const allMessages: MessageEntry[] = [];
  const sessionsMeta: SessionMeta[] = [];
  const prompts: PromptEntry[] = [];
  const drilldown: Record<string, Record<string, DrilldownEntry[]>> = {};

  const modelCounts: Record<string, { msgs: number; input: number; output: number; cache_read: number; cache_write: number }> = {};
  const branchActivity: Record<string, { msgs: number; sessions: Set<string>; projects: Set<string> }> = {};
  const versionCounts: Record<string, number> = {};
  let thinkingCount = 0;
  let totalToolResultTokens = 0;
  let totalConversationTokens = 0;
  let skippedFiles = 0;
  let skippedLines = 0;
  const skillUsage: Record<string, number> = {};
  const slashCommands: Record<string, number> = {};
  const permissionModes: Record<string, number> = {};

  for (const filepath of sessionFiles) {
    const projectDir = path.basename(path.dirname(filepath));
    const projName = cleanProjectName(projectDir);
    const sessionId = path.basename(filepath, ".jsonl");

    const timestamps: string[] = [];
    let userMsgs = 0;
    let assistantMsgs = 0;
    let toolUses = 0;
    let model: string | null = null;
    let entrypoint: string | null = null;
    let gitBranch: string | null = null;
    let sessionInputTokens = 0;
    let sessionOutputTokens = 0;
    let sessionCacheRead = 0;
    let sessionCacheWrite = 0;

    try {
      const content = fs.readFileSync(filepath, "utf-8");
      const lines = content.split("\n");

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;
        let d: Record<string, unknown>;
        try {
          d = JSON.parse(trimmed);
        } catch {
          skippedLines++;
          continue;
        }

        const msgType = d.type as string | undefined;
        const ts = d.timestamp as string | undefined;

        // Track version, branch, permission mode
        const ver = d.version as string | undefined;
        if (ver) {
          versionCounts[ver] = (versionCounts[ver] || 0) + 1;
        }
        const br = d.gitBranch as string | undefined;
        if (br && br !== "HEAD") {
          gitBranch = br;
        }
        const pm = d.permissionMode as string | undefined;
        if (pm) {
          permissionModes[pm] = (permissionModes[pm] || 0) + 1;
        }

        if (msgType === "user" && ts) {
          const rawDate = parseISOTimestamp(ts);
          const dt = applyTzOffset(rawDate, tzOffset!);

          const dateStr = formatDate(dt);
          if (sinceDate && dateStr < sinceDate) continue;

          userMsgs++;
          if (!entrypoint) {
            entrypoint = (d.entrypoint as string) || null;
          }

          const msgData: MessageEntry = {
            timestamp: ts,
            date: dateStr,
            time: formatTime(dt),
            hour: dt.getUTCHours(),
            weekday: getWeekday(dt),
            weekday_name: getWeekdayName(dt),
            month: formatMonth(dt),
            type: "user",
            project: projName,
            session_id: sessionId.substring(0, 8),
          };
          allMessages.push(msgData);
          timestamps.push(ts);

          // Extract prompt text
          const msg = d.message as Record<string, unknown> | undefined;
          let text = "";
          let isToolResult = false;

          if (msg && typeof msg === "object") {
            const msgContent = msg.content;
            if (typeof msgContent === "string") {
              text = msgContent.trim();
            } else if (Array.isArray(msgContent)) {
              let hasText = false;
              for (const c of msgContent) {
                if (c && typeof c === "object") {
                  const co = c as Record<string, unknown>;
                  if (co.type === "text" && typeof co.text === "string" && co.text.trim()) {
                    text += co.text + " ";
                    hasText = true;
                  } else if (co.type === "tool_result") {
                    isToolResult = true;
                  }
                }
              }
              text = text.trim();
              if (!hasText && isToolResult) {
                text = "";
              }
            }
          }

          if (text) {
            const prompt: PromptEntry = {
              text: text.substring(0, 500),
              full_length: text.length,
              project: projName,
              session_id: sessionId.substring(0, 8),
              date: dateStr,
              time: formatTime(dt),
              hour: dt.getUTCHours(),
              weekday: getWeekday(dt),
              category: categorizePrompt(text),
              length_bucket: lengthBucket(text.length),
            };
            prompts.push(prompt);

            if (!drilldown[prompt.date]) drilldown[prompt.date] = {};
            if (!drilldown[prompt.date][projName]) drilldown[prompt.date][projName] = [];
            drilldown[prompt.date][projName].push({
              time: prompt.time,
              text: prompt.text.substring(0, 200),
              category: prompt.category,
              length: prompt.full_length,
            });
          }

          // Track branch activity
          if (gitBranch) {
            if (!branchActivity[gitBranch]) {
              branchActivity[gitBranch] = { msgs: 0, sessions: new Set(), projects: new Set() };
            }
            branchActivity[gitBranch].msgs++;
            branchActivity[gitBranch].sessions.add(sessionId.substring(0, 8));
            branchActivity[gitBranch].projects.add(projName);
          }
        } else if (msgType === "assistant" && ts) {
          const rawDate = parseISOTimestamp(ts);
          const dt = applyTzOffset(rawDate, tzOffset!);

          const dateStr = formatDate(dt);
          if (sinceDate && dateStr < sinceDate) continue;

          assistantMsgs++;
          timestamps.push(ts);

          const msg = d.message as Record<string, unknown> | undefined;
          let msgModel: string | null = null;
          const msgTools: string[] = [];
          let inputTokens = 0;
          let outputTokens = 0;
          let cacheReadTokens = 0;
          let cacheWriteTokens = 0;

          if (msg && typeof msg === "object") {
            msgModel = (msg.model as string) || null;
            if (msgModel) model = msgModel;
            const msgContent = msg.content;
            if (Array.isArray(msgContent)) {
              for (const c of msgContent) {
                if (c && typeof c === "object") {
                  const co = c as Record<string, unknown>;
                  if (co.type === "tool_use") {
                    const toolName = (co.name as string) || "";
                    msgTools.push(toolName);
                    if (toolName.startsWith("mcp__")) {
                      const skillName = toolName.split("__")[1];
                      skillUsage[skillName] = (skillUsage[skillName] || 0) + 1;
                    }
                    if (toolName === "Skill") {
                      const inp = co.input as Record<string, unknown> | undefined;
                      const sn = inp?.skill as string || "unknown";
                      if (sn) {
                        slashCommands[sn] = (slashCommands[sn] || 0) + 1;
                      }
                    }
                  } else if (co.type === "thinking") {
                    thinkingCount++;
                  }
                }
              }
              toolUses += msgTools.length;
            }
            const usage = msg.usage as Record<string, number> | undefined;
            if (usage) {
              inputTokens = usage.input_tokens || 0;
              outputTokens = usage.output_tokens || 0;
              cacheReadTokens = usage.cache_read_input_tokens || 0;
              cacheWriteTokens = usage.cache_creation_input_tokens || 0;
            }
          }

          sessionInputTokens += inputTokens;
          sessionOutputTokens += outputTokens;
          sessionCacheRead += cacheReadTokens;
          sessionCacheWrite += cacheWriteTokens;

          const normModel = msgModel || model || "unknown";
          if (!modelCounts[normModel]) {
            modelCounts[normModel] = { msgs: 0, input: 0, output: 0, cache_read: 0, cache_write: 0 };
          }
          modelCounts[normModel].msgs++;
          modelCounts[normModel].input += inputTokens;
          modelCounts[normModel].output += outputTokens;
          modelCounts[normModel].cache_read += cacheReadTokens;
          modelCounts[normModel].cache_write += cacheWriteTokens;

          if (msgTools.length > 0) {
            totalToolResultTokens += outputTokens;
          } else {
            totalConversationTokens += outputTokens;
          }

          if (gitBranch) {
            if (!branchActivity[gitBranch]) {
              branchActivity[gitBranch] = { msgs: 0, sessions: new Set(), projects: new Set() };
            }
            branchActivity[gitBranch].msgs++;
          }

          allMessages.push({
            timestamp: ts,
            date: dateStr,
            hour: dt.getUTCHours(),
            weekday: getWeekday(dt),
            type: "assistant",
            project: projName,
            session_id: sessionId.substring(0, 8),
            tool_uses: msgTools,
            input_tokens: inputTokens,
            output_tokens: outputTokens,
            model: msgModel || "",
          });
        }
      }
    } catch {
      skippedFiles++;
      continue;
    }

    if (timestamps.length > 0) {
      sessionsMeta.push({
        project: projName,
        session_id: sessionId.substring(0, 8),
        first_ts: timestamps.reduce((a, b) => (a < b ? a : b)),
        last_ts: timestamps.reduce((a, b) => (a > b ? a : b)),
        user_msgs: userMsgs,
        assistant_msgs: assistantMsgs,
        tool_uses: toolUses,
        model,
        entrypoint,
        msg_count: userMsgs + assistantMsgs,
        git_branch: gitBranch,
        input_tokens: sessionInputTokens,
        output_tokens: sessionOutputTokens,
        cache_read_tokens: sessionCacheRead,
        cache_write_tokens: sessionCacheWrite,
      });
    }
  }

  // === Pass 2: Aggregate ===
  const userMessages = allMessages.filter((m) => m.type === "user");
  const asstMessages = allMessages.filter((m) => m.type === "assistant");

  // Daily data
  const dailyUser: Record<string, number> = {};
  const dailyAsst: Record<string, number> = {};
  const dailyTools: Record<string, number> = {};
  const dailyTokens: Record<string, number> = {};
  for (const m of userMessages) {
    dailyUser[m.date] = (dailyUser[m.date] || 0) + 1;
  }
  for (const m of asstMessages) {
    dailyAsst[m.date] = (dailyAsst[m.date] || 0) + 1;
    dailyTools[m.date] = (dailyTools[m.date] || 0) + (m.tool_uses?.length || 0);
    dailyTokens[m.date] = (dailyTokens[m.date] || 0) + (m.output_tokens || 0);
  }

  const allDateSet = new Set([...Object.keys(dailyUser), ...Object.keys(dailyAsst)]);
  const allDates = Array.from(allDateSet).sort();

  const dailyData: DailyEntry[] = allDates.map((d) => ({
    date: d,
    user_msgs: dailyUser[d] || 0,
    assistant_msgs: dailyAsst[d] || 0,
    tool_calls: dailyTools[d] || 0,
    output_tokens: dailyTokens[d] || 0,
    total_msgs: (dailyUser[d] || 0) + (dailyAsst[d] || 0),
  }));

  // Heatmap
  const heatmapCounts: Record<string, number> = {};
  for (const m of userMessages) {
    const key = `${m.weekday}_${m.hour}`;
    heatmapCounts[key] = (heatmapCounts[key] || 0) + 1;
  }
  const heatmapData: HeatmapEntry[] = [];
  for (let wd = 0; wd < 7; wd++) {
    for (let hr = 0; hr < 24; hr++) {
      heatmapData.push({
        weekday: wd,
        hour: hr,
        count: heatmapCounts[`${wd}_${hr}`] || 0,
      });
    }
  }

  // Project stats
  const projectStats: Record<string, {
    user_msgs: number; assistant_msgs: number; tool_calls: number;
    sessions: Set<string>; output_tokens: number;
  }> = {};
  for (const m of allMessages) {
    const p = m.project;
    if (!projectStats[p]) {
      projectStats[p] = { user_msgs: 0, assistant_msgs: 0, tool_calls: 0, sessions: new Set(), output_tokens: 0 };
    }
    projectStats[p].sessions.add(m.session_id);
    if (m.type === "user") {
      projectStats[p].user_msgs++;
    } else {
      projectStats[p].assistant_msgs++;
      projectStats[p].tool_calls += m.tool_uses?.length || 0;
      projectStats[p].output_tokens += m.output_tokens || 0;
    }
  }

  const projectData: ProjectEntry[] = Object.entries(projectStats)
    .map(([p, s]) => ({
      project: p,
      user_msgs: s.user_msgs,
      assistant_msgs: s.assistant_msgs,
      tool_calls: s.tool_calls,
      sessions: s.sessions.size,
      output_tokens: s.output_tokens,
      total_msgs: s.user_msgs + s.assistant_msgs,
    }))
    .sort((a, b) => b.total_msgs - a.total_msgs);

  // Tool stats
  const toolCounts: Record<string, number> = {};
  for (const m of asstMessages) {
    for (const t of m.tool_uses || []) {
      toolCounts[t] = (toolCounts[t] || 0) + 1;
    }
  }
  const toolData: ToolEntry[] = Object.entries(toolCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 20)
    .map(([t, c]) => ({ tool: t, count: c }));

  // Hourly
  const hourlyCounts: Record<number, number> = {};
  for (const m of userMessages) {
    hourlyCounts[m.hour] = (hourlyCounts[m.hour] || 0) + 1;
  }
  const hourlyData: HourlyEntry[] = [];
  for (let h = 0; h < 24; h++) {
    hourlyData.push({ hour: h, count: hourlyCounts[h] || 0 });
  }

  // Session durations
  const sessionDurations: SessionDuration[] = [];
  for (const s of sessionsMeta) {
    try {
      const t1 = parseISOTimestamp(s.first_ts);
      const t2 = parseISOTimestamp(s.last_ts);
      const dur = (t2.getTime() - t1.getTime()) / 60000;
      const t1Local = applyTzOffset(t1, tzOffset!);
      sessionDurations.push({
        session_id: s.session_id,
        project: s.project,
        duration_min: Math.round(dur * 10) / 10,
        user_msgs: s.user_msgs,
        assistant_msgs: s.assistant_msgs,
        tool_uses: s.tool_uses,
        date: formatDate(t1Local),
        start_hour: t1Local.getUTCHours(),
        msgs_per_min: Math.round((s.msg_count / Math.max(dur, 1)) * 100) / 100,
        git_branch: s.git_branch || "",
      });
    } catch {
      continue;
    }
  }

  // Weekly
  const weeklyAgg: Record<string, { user_msgs: number; sessions: Set<string> }> = {};
  for (const m of userMessages) {
    const dt = parseISOTimestamp(m.timestamp);
    const week = getISOWeek(dt);
    if (!weeklyAgg[week]) weeklyAgg[week] = { user_msgs: 0, sessions: new Set() };
    weeklyAgg[week].user_msgs++;
    weeklyAgg[week].sessions.add(m.session_id);
  }
  const weeklyData: WeeklyEntry[] = Object.entries(weeklyAgg)
    .map(([w, d]) => ({ week: w, user_msgs: d.user_msgs, sessions: d.sessions.size }))
    .sort((a, b) => a.week.localeCompare(b.week));

  // Efficiency by start hour
  const hourEff: Record<number, { total_msgs: number; sessions: number; duration_total: number }> = {};
  for (const sd of sessionDurations) {
    const h = sd.start_hour;
    if (!hourEff[h]) hourEff[h] = { total_msgs: 0, sessions: 0, duration_total: 0 };
    hourEff[h].total_msgs += sd.user_msgs + sd.assistant_msgs;
    hourEff[h].sessions++;
    hourEff[h].duration_total += sd.duration_min;
  }
  const efficiencyData: EfficiencyEntry[] = [];
  for (let h = 0; h < 24; h++) {
    const e = hourEff[h];
    if (e && e.sessions > 0) {
      efficiencyData.push({
        hour: h,
        avg_msgs_per_session: Math.round((e.total_msgs / e.sessions) * 10) / 10,
        avg_duration: Math.round((e.duration_total / e.sessions) * 10) / 10,
        sessions: e.sessions,
      });
    }
  }

  // Working hours estimate
  const dailySpans: Record<string, Date[]> = {};
  for (const m of userMessages) {
    const dt = applyTzOffset(parseISOTimestamp(m.timestamp), tzOffset!);
    const dateStr = formatDate(dt);
    if (!dailySpans[dateStr]) dailySpans[dateStr] = [];
    dailySpans[dateStr].push(dt);
  }

  const workDays: WorkDay[] = [];
  for (const day of Object.keys(dailySpans).sort()) {
    const times = dailySpans[day].sort((a, b) => a.getTime() - b.getTime());
    const spanHrs = (times[times.length - 1].getTime() - times[0].getTime()) / 3600000;
    let activeSecs = 120;
    for (let i = 1; i < times.length; i++) {
      const gap = (times[i].getTime() - times[i - 1].getTime()) / 1000;
      activeSecs += Math.min(gap, 1800);
    }
    const activeHrs = activeSecs / 3600;
    workDays.push({
      date: day,
      first: formatTime(times[0]),
      last: formatTime(times[times.length - 1]),
      span_hrs: Math.round(spanHrs * 10) / 10,
      active_hrs: Math.round(activeHrs * 10) / 10,
      prompts: times.length,
    });
  }

  // Prompt analysis
  const catCounts: Record<string, number> = {};
  const lbCounts: Record<string, number> = {};
  const projQuality: Record<string, {
    count: number; total_len: number; confirms: number;
    detailed: number; cats: Record<string, number>;
  }> = {};

  for (const p of prompts) {
    catCounts[p.category] = (catCounts[p.category] || 0) + 1;
    lbCounts[p.length_bucket] = (lbCounts[p.length_bucket] || 0) + 1;
    if (!projQuality[p.project]) {
      projQuality[p.project] = { count: 0, total_len: 0, confirms: 0, detailed: 0, cats: {} };
    }
    const pq = projQuality[p.project];
    pq.count++;
    pq.total_len += p.full_length;
    if (p.category === "confirmation" || p.category === "micro") {
      pq.confirms++;
    }
    if (p.full_length > 100) {
      pq.detailed++;
    }
    pq.cats[p.category] = (pq.cats[p.category] || 0) + 1;
  }

  const totalPrompts = prompts.length;
  const avgLength = totalPrompts > 0
    ? Math.round(prompts.reduce((s, p) => s + p.full_length, 0) / totalPrompts)
    : 0;

  const categories: CategoryEntry[] = Object.entries(catCounts)
    .sort((a, b) => b[1] - a[1])
    .map(([c, n]) => ({
      cat: c,
      count: n,
      pct: Math.round((n / Math.max(totalPrompts, 1)) * 1000) / 10,
    }));

  const bucketOrder = [
    "micro (<20)", "short (20-50)", "medium (50-150)",
    "detailed (150-500)", "comprehensive (500+)",
  ];
  const lengthBuckets: LengthBucketEntry[] = bucketOrder.map((b) => ({
    bucket: b,
    count: lbCounts[b] || 0,
    pct: Math.round(((lbCounts[b] || 0) / Math.max(totalPrompts, 1)) * 1000) / 10,
  }));

  const projectQualityArr: ProjectQuality[] = Object.entries(projQuality)
    .filter(([, d]) => d.count >= 5)
    .map(([p, d]) => {
      const topCatEntries = Object.entries(d.cats);
      const topCat = topCatEntries.length > 0
        ? topCatEntries.reduce((a, b) => (b[1] > a[1] ? b : a))[0]
        : "unknown";
      return {
        project: p,
        count: d.count,
        avg_len: Math.round(d.total_len / d.count),
        confirm_pct: Math.round((d.confirms / d.count) * 1000) / 10,
        detailed_pct: Math.round((d.detailed / d.count) * 1000) / 10,
        top_cat: topCat,
      };
    })
    .sort((a, b) => b.count - a.count);

  const analysis: Analysis = {
    total_prompts: totalPrompts,
    avg_length: avgLength,
    categories,
    length_buckets: lengthBuckets,
    project_quality: projectQualityArr,
  };

  // === Model breakdown ===
  const totalOutput = Object.values(modelCounts).reduce((s, v) => s + v.output, 0);
  const totalInput = Object.values(modelCounts).reduce((s, v) => s + v.input, 0);
  const totalCacheRead = Object.values(modelCounts).reduce((s, v) => s + v.cache_read, 0);
  const totalCacheWrite = Object.values(modelCounts).reduce((s, v) => s + v.cache_write, 0);

  const modelBreakdown: ModelBreakdown[] = Object.entries(modelCounts)
    .sort((a, b) => b[1].msgs - a[1].msgs)
    .map(([rawModel, counts]) => {
      const display = normalizeModelName(rawModel);
      const costTier = matchModelCost(rawModel);
      const cost =
        (counts.input / 1_000_000) * costTier.input +
        (counts.output / 1_000_000) * costTier.output +
        (counts.cache_read / 1_000_000) * costTier.cache_read +
        (counts.cache_write / 1_000_000) * costTier.cache_write;
      return {
        model: rawModel,
        display,
        msgs: counts.msgs,
        input_tokens: counts.input,
        output_tokens: counts.output,
        cache_read_tokens: counts.cache_read,
        cache_write_tokens: counts.cache_write,
        estimated_cost: Math.round(cost * 100) / 100,
      };
    });

  // === Cost estimation ===
  let totalCost = modelBreakdown.reduce((s, m) => s + m.estimated_cost, 0);

  // === Subagent analysis ===
  const subagentData = parseSubagents(claudeDir, tzOffset!);

  // Add subagent costs
  let subagentCost = 0;
  for (const [rawModel, tokens] of Object.entries(subagentData.model_tokens)) {
    const costTier = matchModelCost(rawModel);
    subagentCost +=
      (tokens.input / 1_000_000) * costTier.input +
      (tokens.output / 1_000_000) * costTier.output +
      (tokens.cache_read / 1_000_000) * costTier.cache_read;
  }
  subagentData.estimated_cost = Math.round(subagentCost * 100) / 100;
  totalCost += subagentCost;

  // === Git branch data ===
  const branchData: BranchEntry[] = Object.entries(branchActivity)
    .map(([br, d]) => ({
      branch: br,
      msgs: d.msgs,
      sessions: d.sessions.size,
      projects: Array.from(d.projects),
    }))
    .sort((a, b) => b.msgs - a.msgs)
    .slice(0, 20);

  // === Context efficiency ===
  const totalAllOutput = totalOutput + subagentData.total_subagent_output_tokens;
  const contextEfficiency: ContextEfficiency = {
    tool_output_tokens: totalToolResultTokens,
    conversation_tokens: totalConversationTokens,
    tool_pct: Math.round((totalToolResultTokens / Math.max(totalOutput, 1)) * 1000) / 10,
    conversation_pct: Math.round((totalConversationTokens / Math.max(totalOutput, 1)) * 1000) / 10,
    thinking_blocks: thinkingCount,
    subagent_output_tokens: subagentData.total_subagent_output_tokens,
    subagent_pct: Math.round(
      (subagentData.total_subagent_output_tokens / Math.max(totalAllOutput, 1)) * 1000
    ) / 10,
  };

  // === Version tracking ===
  const versionData: VersionEntry[] = Object.entries(versionCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([v, c]) => ({ version: v, count: c }));

  // === Skill/MCP usage ===
  const skillData: SkillEntry[] = Object.entries(skillUsage)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([s, c]) => ({ skill: s, count: c }));

  // === Slash command usage ===
  const slashCommandData: SlashCommandEntry[] = Object.entries(slashCommands)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([cmd, c]) => ({ command: cmd, count: c }));

  // Config
  const config = parseConfig(claudeDir);

  const summary: DashboardSummary = {
    total_sessions: sessionsMeta.length,
    total_user_msgs: userMessages.length,
    total_assistant_msgs: asstMessages.length,
    total_tool_calls: asstMessages.reduce((s, m) => s + (m.tool_uses?.length || 0), 0),
    total_output_tokens: totalOutput,
    total_input_tokens: totalInput,
    total_cache_read_tokens: totalCacheRead,
    total_cache_write_tokens: totalCacheWrite,
    date_range_start: allDates.length > 0 ? allDates[0] : "",
    date_range_end: allDates.length > 0 ? allDates[allDates.length - 1] : "",
    since_date: sinceDate || "",
    unique_projects: Object.keys(projectStats).length,
    unique_tools: Object.keys(toolCounts).length,
    avg_session_duration:
      sessionDurations.length > 0
        ? Math.round(
            (sessionDurations.reduce((s, sd) => s + sd.duration_min, 0) / sessionDurations.length) *
              10
          ) / 10
        : 0,
    tz_offset: tzOffset!,
    tz_label: `UTC${tzOffset! >= 0 ? "+" : ""}${tzOffset}`,
    estimated_cost: Math.round(totalCost * 100) / 100,
    skipped_files: skippedFiles,
    skipped_lines: skippedLines,
  };

  return {
    dashboard: {
      summary,
      daily: dailyData,
      heatmap: heatmapData,
      projects: projectData,
      tools: toolData,
      hourly: hourlyData,
      sessions: sessionDurations,
      weekly: weeklyData,
      efficiency: efficiencyData,
    },
    drilldown,
    analysis,
    prompts,
    work_days: workDays,
    models: modelBreakdown,
    subagents: subagentData,
    branches: branchData,
    context_efficiency: contextEfficiency,
    versions: versionData,
    skills: skillData,
    slash_commands: slashCommandData,
    permission_modes: permissionModes,
    config,
  };
}

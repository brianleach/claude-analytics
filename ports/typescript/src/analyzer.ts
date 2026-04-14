/**
 * Heuristic + AI-powered prompt analysis and recommendations.
 */

import * as fs from "fs";
import * as https from "https";
import * as path from "path";

import type {
  Analysis,
  DashboardSummary,
  WorkDay,
  PromptEntry,
  ModelBreakdown,
  SubagentData,
  ContextEfficiency,
  BranchEntry,
  SkillEntry,
  ParsedData,
} from "./parser";

// ============================================================
// Interfaces
// ============================================================

export interface Recommendation {
  title: string;
  severity: "high" | "medium" | "low";
  body: string;
  metric: string;
  example: string;
  rec_source?: string;
}

export interface RecommendationResult {
  recommendations: Recommendation[];
  source: string;
}

interface RuleCondition {
  metric?: string;
  operator?: string;
  threshold?: number;
  threshold_metric?: string;
}

interface HeuristicRule {
  id: string;
  title: string;
  section: string;
  condition: {
    type: string;
    metric?: string;
    metrics?: string[];
    computed_metric?: string;
    operator?: string;
    threshold?: number;
    conditions?: RuleCondition[];
    excludes?: string;
  };
  severity: string;
  severity_override?: {
    condition: RuleCondition;
    severity: string;
  };
  body_template?: string;
  body_variants?: Record<string, string>;
  body_variant_condition?: RuleCondition & { variant: string };
  metric_template: string;
  example_type?: string;
  example_category?: string;
  example_max_count?: number;
  example_preamble?: string;
  example_suggestion?: string;
  fallback_example: string;
}

// ============================================================
// Helpers
// ============================================================

function findExamplePrompts(
  prompts: PromptEntry[],
  category: string,
  maxCount = 3,
  maxLen = 150
): string[] {
  const matches = prompts.filter(
    (p) => p.category === category && p.text.length > 15
  );
  matches.sort((a, b) => a.full_length - b.full_length);
  return matches.slice(0, maxCount).map((p) => p.text.substring(0, maxLen));
}

function findShortPrompts(
  prompts: PromptEntry[],
  maxChars = 50,
  maxCount = 5
): string[] {
  let short = prompts.filter(
    (p) => p.full_length < maxChars && p.text.trim().length > 3
  );
  if (short.length > maxCount) {
    const step = Math.floor(short.length / maxCount);
    short = Array.from({ length: maxCount }, (_, i) => short[i * step]);
  }
  return short.map((p) => p.text.substring(0, 80));
}

let rulesCache: HeuristicRule[] | null = null;

function loadRules(): HeuristicRule[] {
  if (rulesCache) return rulesCache;
  const rulesPath = path.resolve(__dirname, "..", "..", "..", "shared", "heuristic_rules.json");
  rulesCache = JSON.parse(fs.readFileSync(rulesPath, "utf-8"));
  return rulesCache!;
}

function renderTemplate(template: string, values: Record<string, number>): string {
  return template.replace(/\{\{(\w+)(?::([^}]+))?\}\}/g, (_, key, fmt) => {
    const val = values[key];
    if (val === undefined) return "";
    if (fmt) {
      // Handle :.0f format
      const match = fmt.match(/^\.(\d+)f$/);
      if (match) return val.toFixed(parseInt(match[1]));
    }
    return String(val);
  });
}

function checkCondition(cond: RuleCondition, values: Record<string, number>): boolean {
  const metricVal = values[cond.metric!] || 0;
  const threshold = cond.threshold_metric
    ? (values[cond.threshold_metric] || 0)
    : (cond.threshold ?? 0);
  switch (cond.operator) {
    case ">": return metricVal > threshold;
    case "<": return metricVal < threshold;
    case ">=": return metricVal >= threshold;
    case "<=": return metricVal <= threshold;
    default: return false;
  }
}

// ============================================================
// Heuristic recommendations
// ============================================================

export function getHeuristicRecommendations(
  analysis: Analysis,
  summary: DashboardSummary,
  workDays: WorkDay[] | null,
  prompts?: PromptEntry[] | null,
  models?: ModelBreakdown[] | null,
  subagents?: SubagentData | null,
  contextEfficiency?: ContextEfficiency | null,
  branches?: BranchEntry[] | null,
  skills?: SkillEntry[] | null,
  permissionModes?: Record<string, number> | null
): Recommendation[] {
  const rules = loadRules();
  const recs: Recommendation[] = [];
  const total = analysis.total_prompts;
  const avgLen = analysis.avg_length;
  const promptList = prompts || [];
  const modelList = models || [];
  const sa = subagents || ({} as SubagentData);
  const ce = contextEfficiency || ({} as ContextEfficiency);
  const skillList = skills || [];
  const pm = permissionModes || {};

  const catMap: Record<string, { cat: string; count: number; pct: number }> = {};
  for (const c of analysis.categories) catMap[c.cat] = c;

  const lbMap: Record<string, { bucket: string; count: number; pct: number }> = {};
  for (const l of analysis.length_buckets) lbMap[l.bucket] = l;

  const microPct = lbMap["micro (<20)"]?.pct || 0;
  const shortPct = lbMap["short (20-50)"]?.pct || 0;
  const debugPct = catMap["debugging"]?.pct || 0;
  const testPct = catMap["testing"]?.pct || 0;
  const refPct = catMap["refactoring"]?.pct || 0;
  const qPct = catMap["question"]?.pct || 0;
  const buildPct = catMap["building"]?.pct || 0;
  const confirmPct = catMap["confirmation"]?.pct || 0;

  // Computed metrics
  const avgMsgs = summary.total_user_msgs / Math.max(summary.total_sessions, 1);
  const totalSessions = summary.total_sessions;

  let opusPct = 0;
  if (modelList.length > 0) {
    const opusModel = modelList.find((m) => m.display === "Opus");
    const totalCost = summary.estimated_cost || 0;
    if (opusModel && totalCost > 0) {
      opusPct = Math.round((opusModel.estimated_cost / totalCost) * 100);
    }
  }

  const saCount = sa.total_count || 0;
  const saTypes = sa.type_counts || {};
  const exploreCount = saTypes["Explore"] || 0;
  const gpCount = saTypes["general-purpose"] || 0;
  const compactionCount = sa.compaction_count || 0;

  const toolPct = ce.tool_pct || 0;
  const conversationPct = ce.conversation_pct || 0;
  const thinking = ce.thinking_blocks || 0;
  const thinkingPerSession = thinking / Math.max(totalSessions, 1);

  const skillCount = skillList.length;

  const defaultPm = pm["default"] || 0;
  const totalPm = Object.values(pm).reduce((s, v) => s + v, 0) || 1;
  const defaultPmRatio = defaultPm / totalPm;
  const defaultPmPct = defaultPmRatio * 100;

  const formatPromptCount = promptList.filter((p) =>
    ["lint", "format", "prettier", "eslint", "formatting"].some((w) =>
      p.text.toLowerCase().includes(w)
    )
  ).length;

  const longSessionCount = (workDays || []).filter((s) => (s.active_hrs || 0) > 4).length;

  const values: Record<string, number> = {
    total, avg_len: avgLen,
    micro_pct: microPct, short_pct: shortPct,
    micro_short_pct: microPct + shortPct,
    debug_pct: debugPct, test_pct: testPct,
    ref_pct: refPct, q_pct: qPct,
    build_pct: buildPct, confirm_pct: confirmPct,
    avg_msgs: avgMsgs, total_sessions: totalSessions,
    opus_pct: opusPct,
    sa_count: saCount, explore_count: exploreCount, gp_count: gpCount,
    compaction_count: compactionCount,
    tool_pct: toolPct, conversation_pct: conversationPct,
    thinking, thinking_per_session: thinkingPerSession,
    skill_count: skillCount,
    default_pm_ratio: defaultPmRatio, default_pm_pct: defaultPmPct,
    format_prompt_count: formatPromptCount,
    long_session_count: longSessionCount,
  };

  const triggeredIds = new Set<string>();

  for (const rule of rules) {
    const cond = rule.condition;

    // Evaluate condition
    if (cond.type === "simple") {
      if (!checkCondition(cond as RuleCondition, values)) continue;
    } else if (cond.type === "sum_gt") {
      const total = (cond.metrics || []).reduce((s, m) => s + (values[m] || 0), 0);
      if (total <= (cond.threshold ?? 0)) continue;
    } else if (cond.type === "or") {
      if (!(cond.conditions || []).some((c) => checkCondition(c, values))) continue;
    } else if (cond.type === "compound_and") {
      if (!(cond.conditions || []).every((c) => checkCondition(c, values))) continue;
      if (cond.excludes && triggeredIds.has(cond.excludes)) continue;
    } else if (cond.type === "computed") {
      if (!checkCondition(
        { metric: cond.computed_metric, operator: cond.operator, threshold: cond.threshold },
        values
      )) continue;
    } else {
      continue;
    }

    triggeredIds.add(rule.id);

    // Severity
    let severity = rule.severity as "high" | "medium" | "low";
    if (rule.severity_override) {
      if (checkCondition(rule.severity_override.condition, values)) {
        severity = rule.severity_override.severity as "high" | "medium" | "low";
      }
    }

    // Body
    let body: string;
    if (rule.body_variants) {
      let variant = "default";
      if (rule.body_variant_condition && checkCondition(rule.body_variant_condition, values)) {
        variant = rule.body_variant_condition.variant;
      }
      body = renderTemplate(rule.body_variants[variant], values);
    } else {
      body = renderTemplate(rule.body_template!, values);
    }

    const metric = renderTemplate(rule.metric_template, values);

    // Example
    let example = "";
    if (rule.example_type === "short_prompts") {
      const shortExamples = findShortPrompts(promptList);
      if (shortExamples.length > 0) {
        example = rule.example_preamble + "\n";
        for (const ex of shortExamples.slice(0, 3)) {
          example += `  > "${ex}"\n`;
        }
        example += "\n" + rule.example_suggestion;
      }
    } else if (rule.example_type === "category_prompts") {
      const maxCount = rule.example_max_count || 3;
      const catExamples = findExamplePrompts(promptList, rule.example_category!, maxCount);
      if (catExamples.length > 0) {
        example = rule.example_preamble + "\n";
        for (const ex of catExamples.slice(0, maxCount)) {
          example += `  > "${ex}"\n`;
        }
        example += "\n" + rule.example_suggestion;
      }
    }

    if (!example) {
      example = rule.fallback_example;
    }

    recs.push({ title: rule.title, severity, body, metric, example });
  }

  return recs;
}

// ============================================================
// AI-powered recommendations (Claude API)
// ============================================================

function buildAiPrompt(
  analysis: Analysis,
  summary: DashboardSummary,
  promptsSample: PromptEntry[],
  workDays: WorkDay[],
  models: ModelBreakdown[],
  subagents: SubagentData,
  contextEfficiency: ContextEfficiency,
  branches: BranchEntry[],
  skills: SkillEntry[],
  permissionModes: Record<string, number>
): string {
  const catSummary = analysis.categories
    .slice(0, 8)
    .map((c) => `${c.cat}: ${c.pct}%`)
    .join(", ");
  const lenSummary = analysis.length_buckets
    .map((l) => `${l.bucket}: ${l.pct}%`)
    .join(", ");

  // Sample prompts by category
  const sampleByCat: Record<string, Array<{ text: string; length: number; project: string }>> = {};
  for (const p of promptsSample) {
    const cat = p.category;
    if (!sampleByCat[cat]) sampleByCat[cat] = [];
    if (sampleByCat[cat].length < 5) {
      sampleByCat[cat].push({
        text: p.text.substring(0, 300),
        length: p.full_length || p.text.length,
        project: p.project || "",
      });
    }
  }

  let sampleText = "";
  const sortedCats = Object.entries(sampleByCat).sort((a, b) => b[1].length - a[1].length);
  for (const [cat, samples] of sortedCats) {
    sampleText += `\n### ${cat} (${samples.length} samples)\n`;
    for (const s of samples) {
      sampleText += `  [${s.project}] (${s.length}ch) "${s.text}"\n`;
    }
  }

  // Work pattern
  let workSummary = "No work pattern data";
  if (workDays.length > 0) {
    const totalActive = workDays.reduce((s, d) => s + (d.active_hrs || 0), 0);
    const avgDaily = totalActive / workDays.length;
    const avgPrompts = workDays.reduce((s, d) => s + d.prompts, 0) / workDays.length;
    workSummary = `Active days: ${workDays.length}, avg active hours/day: ${avgDaily.toFixed(1)}h, avg prompts/day: ${avgPrompts.toFixed(0)}, total active hours: ${totalActive.toFixed(1)}h`;
  }

  // Model usage
  let modelText = "No model data";
  if (models.length > 0) {
    modelText = models
      .filter((m) => m.msgs > 0)
      .map((m) => `  ${m.display}: ${m.msgs} msgs, $${m.estimated_cost.toFixed(2)} estimated cost`)
      .join("\n");
  }

  // Subagent usage
  let saText = "No subagent data";
  if (subagents && (subagents.total_count || 0) > 0) {
    saText =
      `Total: ${subagents.total_count}, Compactions: ${subagents.compaction_count}\n` +
      `  Types: ${JSON.stringify(subagents.type_counts || {})}\n` +
      `  Subagent cost: $${(subagents.estimated_cost || 0).toFixed(2)}`;
  }

  // Context efficiency
  let ceText = "No context data";
  if (contextEfficiency) {
    ceText =
      `Tool output: ${contextEfficiency.tool_pct || 0}%, Conversation: ${contextEfficiency.conversation_pct || 0}%, ` +
      `Thinking blocks: ${contextEfficiency.thinking_blocks || 0}, ` +
      `Subagent output share: ${contextEfficiency.subagent_pct || 0}%`;
  }

  // Branch summary
  let branchText = "No branch data";
  if (branches.length > 0) {
    branchText = branches
      .slice(0, 10)
      .map((b) => `  ${b.branch}: ${b.msgs} msgs, ${b.sessions} sessions`)
      .join("\n");
  }

  // Permission modes
  let pmText = "No permission data";
  const pmEntries = Object.entries(permissionModes);
  if (pmEntries.length > 0) {
    const totalPm = pmEntries.reduce((s, [, v]) => s + v, 0);
    pmText = pmEntries
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k}: ${v} (${Math.round((v / totalPm) * 100)}%)`)
      .join(", ");
  }

  return `You are a senior Claude Code power user coaching another developer. You know Claude Code deeply — its features, hidden capabilities, and common anti-patterns. Your job: look at this developer's ACTUAL usage data and tell them exactly what to change.

Rules for your recommendations:
- NEVER be generic. Every sentence must reference a specific number, project name, or prompt from their data.
- Quote their ACTUAL prompts in examples (from the samples below) and rewrite them better.
- Know Claude Code features: CLAUDE.md files, /model switching (opus/sonnet/haiku), subagent types (Explore for search, general-purpose for code changes), permission modes, hooks, extended thinking, MCP integrations, /compact command, worktrees.
- Think in terms of ROI: what change saves them the most time or money per effort?
- Be blunt. If they're wasting money, say so with the dollar amount. If their prompts suck, show them why.

## Their Data

### Overview
- ${analysis.total_prompts} prompts across ${summary.total_sessions} sessions, ${summary.unique_projects} projects
- Date range: ${summary.date_range_start} to ${summary.date_range_end}
- Average prompt length: ${analysis.avg_length} chars
- Estimated API cost: $${(summary.estimated_cost || 0).toFixed(2)}
- ${workSummary}

### Prompt Categories (what they ask Claude to do)
${catSummary}

### Prompt Length Distribution
${lenSummary}

### Model Usage & Cost
${modelText}

### Subagent Usage
${saText}

### Context Window Efficiency
${ceText}

### Git Branch Activity
${branchText}

### Permission Modes
${pmText}

### Project Quality Scores (per-project prompt patterns)
${JSON.stringify(analysis.project_quality.slice(0, 8), null, 2)}

### REAL Prompts From This User (use these in before/after examples)
${sampleText}

## Expert Best Practices (from Boris Cherny, Claude Code creator)
Reference these when the user's data shows they're missing these patterns:
- PostToolUse hooks to auto-format code (handles the last 10% of formatting, avoids CI failures)
- /permissions to pre-allow safe commands instead of --dangerously-skip-permissions. Check into .claude/settings.json and share with team.
- MCP integrations for Slack, BigQuery, Sentry, etc. — Claude should use ALL your tools, not just code.
- For long-running tasks: verify work with a background agent, or use an AgentStop hook.
- THE #1 TIP: Give Claude a way to verify its work. If it can run tests after every change, output quality jumps 2-3x.
- CLAUDE.md should contain: project conventions, how to run tests, what to do automatically (don't ask).

## Output Format

Return a JSON array of 8-10 objects. Each object:
- "title": imperative, max 8 words, no fluff (e.g. "Stop using Opus for grep" not "Consider optimizing model selection")
- "severity": "high" (costs real money/time NOW), "medium" (compounds over weeks), "low" (polish)
- "body": 2-4 sentences. MUST cite specific numbers from their data. Explain what's wrong AND the concrete impact (dollars saved, minutes recovered, bugs prevented).
- "metric": their current number | target (e.g. "72% Opus spend | target: <30%")
- "example": Show a REAL prompt they wrote, then show the improved version. Use this format:
  "Before: [their actual prompt]\\nAfter: [your improved version]\\nWhy: [one sentence explaining the difference]"
  OR show a Claude Code command/config they should use.

Ordering: HIGH items first, then MEDIUM, then LOW.

Focus areas (skip if their data doesn't support it):
1. Money: Are they burning cash on expensive models for simple tasks?
2. Prompt craft: Show before/after rewrites of their weakest prompts
3. Feature gaps: Claude Code features they're clearly not using (based on absence in data)
4. Session hygiene: Are sessions too long? Too many compactions? Context bloat?
5. Workflow: Could they batch, parallelize, or automate?
6. Testing/quality: Are they debugging more than building?

Return ONLY the JSON array. No markdown fences, no commentary outside the array.`;
}

/** Make an HTTPS POST request using Node's built-in https module. */
function httpsPost(
  url: string,
  headers: Record<string, string>,
  body: string
): Promise<{ status: number; data: string }> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const options: https.RequestOptions = {
      hostname: parsed.hostname,
      port: parsed.port || 443,
      path: parsed.pathname,
      method: "POST",
      headers: {
        ...headers,
        "Content-Length": Buffer.byteLength(body).toString(),
      },
    };

    const req = https.request(options, (res) => {
      const chunks: Buffer[] = [];
      res.on("data", (chunk: Buffer) => chunks.push(chunk));
      res.on("end", () => {
        resolve({
          status: res.statusCode || 0,
          data: Buffer.concat(chunks).toString("utf-8"),
        });
      });
    });

    req.on("error", reject);
    req.write(body);
    req.end();
  });
}

/** Spinner that shows rotating progress phases on stdout. */
function startSpinner(): { stop: () => void } {
  const phases = [
    "Analyzing prompt patterns",
    "Evaluating model usage",
    "Reviewing session efficiency",
    "Checking workflow patterns",
    "Generating personalized tips",
  ];
  const chars = "\u280B\u2819\u2839\u2838\u283C\u2834\u2826\u2827\u2807\u280F";
  let i = 0;
  const t0 = Date.now();
  let stopped = false;

  const interval = setInterval(() => {
    if (stopped) return;
    const elapsed = Math.floor((Date.now() - t0) / 1000);
    const phase = phases[Math.min(Math.floor(elapsed / 10), phases.length - 1)];
    const ch = chars[i % chars.length];
    process.stdout.write(`\r  ${ch} ${phase}... (${elapsed}s)`);
    i++;
  }, 100);

  return {
    stop() {
      stopped = true;
      clearInterval(interval);
      process.stdout.write("\r" + " ".repeat(60) + "\r");
    },
  };
}

export async function getAiRecommendations(
  analysis: Analysis,
  summary: DashboardSummary,
  promptsSample: PromptEntry[],
  workDays: WorkDay[],
  models: ModelBreakdown[],
  subagents: SubagentData,
  contextEfficiency: ContextEfficiency,
  branches: BranchEntry[],
  skills: SkillEntry[],
  permissionModes: Record<string, number>
): Promise<{ recs: Recommendation[] | null; error: string | null }> {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return { recs: null, error: "ANTHROPIC_API_KEY not set" };
  }

  const prompt = buildAiPrompt(
    analysis, summary, promptsSample, workDays,
    models, subagents, contextEfficiency, branches, skills, permissionModes
  );

  const requestBody = JSON.stringify({
    model: "claude-opus-4-6",
    max_tokens: 4000,
    messages: [{ role: "user", content: prompt }],
  });

  const spinner = startSpinner();

  try {
    const response = await httpsPost(
      "https://api.anthropic.com/v1/messages",
      {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
      },
      requestBody
    );

    spinner.stop();

    if (response.status !== 200) {
      const errBody = response.data;
      let errMsg = `API returned status ${response.status}`;
      try {
        const parsed = JSON.parse(errBody);
        if (parsed.error?.message) errMsg = parsed.error.message;
      } catch {
        // keep default error message
      }
      return { recs: null, error: errMsg };
    }

    const responseData = JSON.parse(response.data);
    let text: string = responseData.content?.[0]?.text || "";
    text = text.trim();

    let recs: Recommendation[];
    if (text.startsWith("[")) {
      recs = JSON.parse(text);
    } else {
      const start = text.indexOf("[");
      const end = text.lastIndexOf("]") + 1;
      if (start >= 0 && end > start) {
        recs = JSON.parse(text.substring(start, end));
      } else {
        return { recs: null, error: "Could not parse API response as JSON" };
      }
    }

    return { recs, error: null };
  } catch (e: unknown) {
    spinner.stop();
    const msg = e instanceof Error ? e.message : String(e);
    return { recs: null, error: msg };
  }
}

// ============================================================
// Main entry point
// ============================================================

export async function generateRecommendations(
  data: ParsedData,
  useApi = true
): Promise<RecommendationResult> {
  const analysis = data.analysis;
  const summary = data.dashboard.summary;
  const workDays = data.work_days || [];
  const promptList = data.prompts || [];
  const modelList = data.models || [];
  const sa = data.subagents || ({} as SubagentData);
  const ce = data.context_efficiency || ({} as ContextEfficiency);
  const branchList = data.branches || [];
  const skillList = data.skills || [];
  const pm = data.permission_modes || {};

  // Always generate heuristic recs
  const heuristicRecs = getHeuristicRecommendations(
    analysis,
    summary,
    workDays,
    promptList,
    modelList,
    sa,
    ce,
    branchList,
    skillList,
    pm
  );

  if (!useApi) {
    for (const r of heuristicRecs) {
      r.rec_source = "heuristic";
    }
    return { recommendations: heuristicRecs, source: "heuristic" };
  }

  const { recs: aiRecs, error } = await getAiRecommendations(
    analysis, summary, promptList.slice(0, 80), workDays,
    modelList, sa, ce, branchList, skillList, pm
  );

  if (aiRecs) {
    for (const r of aiRecs) {
      r.rec_source = "ai";
    }
    for (const r of heuristicRecs) {
      r.rec_source = "heuristic";
    }
    const merged = [...aiRecs, ...heuristicRecs];
    console.log(`  ${aiRecs.length} AI + ${heuristicRecs.length} heuristic = ${merged.length} recommendations`);
    return { recommendations: merged, source: "ai" };
  } else {
    console.log(`  AI analysis unavailable (${error}), using heuristic analysis`);
    for (const r of heuristicRecs) {
      r.rec_source = "heuristic";
    }
    return { recommendations: heuristicRecs, source: "heuristic" };
  }
}

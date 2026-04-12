/**
 * Heuristic prompt analysis and recommendations.
 */

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
  const recs: Recommendation[] = [];
  const total = analysis.total_prompts;
  const avgLen = analysis.avg_length;
  const promptList = prompts || [];
  const modelList = models || [];
  const sa = subagents || ({} as SubagentData);
  const ce = contextEfficiency || ({} as ContextEfficiency);
  const branchList = branches || [];
  const skillList = skills || [];

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
  const editPct = catMap["editing"]?.pct || 0;

  // ──────────────────────────────────────────────
  // PROMPTING RECOMMENDATIONS
  // ──────────────────────────────────────────────

  // 1. Prompt specificity
  if (microPct + shortPct > 25) {
    const shortExamples = findShortPrompts(promptList);
    let exampleBlock = "";
    if (shortExamples.length > 0) {
      exampleBlock = "Your short prompts include:\n";
      for (const ex of shortExamples.slice(0, 3)) {
        exampleBlock += `  > "${ex}"\n`;
      }
      exampleBlock += "\nTry instead:\n";
      exampleBlock +=
        '"Fix the login form in src/auth/LoginForm.tsx — it shows a blank ' +
        "screen after submitting valid credentials. The handleSubmit callback " +
        "should redirect to /dashboard but router.push isn't firing.\"";
    }

    let bodyText: string;
    let severity: "high" | "medium";
    if (avgLen > 200) {
      bodyText =
        `${(microPct + shortPct).toFixed(0)}% of your prompts are under 50 characters ` +
        `(though your avg is ${avgLen} chars — a bimodal pattern). ` +
        "Those short prompts are often confirmations or follow-ups that " +
        "force extra round-trips. Try batching context into fewer, richer prompts.";
      severity = "medium";
    } else {
      bodyText =
        `${(microPct + shortPct).toFixed(0)}% of your prompts are under 50 characters. ` +
        "Short prompts force Claude to guess, burning tokens on clarification. " +
        "Include: file path, expected vs actual behavior, and constraints. " +
        "A specific 100-char prompt saves 5 rounds of back-and-forth.";
      severity = "high";
    }

    recs.push({
      title: "Front-load context in your prompts",
      severity,
      body: bodyText,
      metric: `your avg: ${avgLen} chars | ${(microPct + shortPct).toFixed(0)}% under 50 chars`,
      example:
        exampleBlock ||
        'Instead of "fix the bug", try:\n' +
          '"Fix the login form in src/auth/LoginForm.tsx — blank screen after ' +
          'submit. handleSubmit should redirect to /dashboard."',
    });
  }

  // 2. High confirmation ratio
  if (confirmPct > 15) {
    const confirmExamples = findExamplePrompts(promptList, "confirmation");
    let exampleBlock = "";
    if (confirmExamples.length > 0) {
      exampleBlock = "Your confirmation prompts include:\n";
      for (const ex of confirmExamples.slice(0, 3)) {
        exampleBlock += `  > "${ex}"\n`;
      }
      exampleBlock += "\nEliminate these by adding to CLAUDE.md:\n";
      exampleBlock +=
        "- Auto-fix lint errors without asking\n" +
        "- Run tests after every code change\n" +
        "- Commit with descriptive messages, don't ask for approval";
    }

    recs.push({
      title: "Reduce confirmation ping-pong",
      severity: "medium",
      body:
        `${confirmPct}% of your prompts are confirmations (yes, ok, go ahead, etc). ` +
        "This suggests Claude is asking for permission too often. Set up a " +
        "CLAUDE.md with your conventions so Claude can act autonomously, and " +
        "use permission mode flags to reduce approval prompts.",
      metric: `${confirmPct}% confirmations | target: <10%`,
      example:
        exampleBlock ||
        "Add to CLAUDE.md:\n" +
          "- Auto-fix lint errors without asking\n" +
          "- Run tests after every code change\n" +
          "- Commit with descriptive messages, don't ask for approval",
    });
  }

  // 3. Debug ratio
  if (debugPct > 12) {
    const debugExamples = findExamplePrompts(promptList, "debugging");
    let exampleBlock = "";
    if (debugExamples.length > 0) {
      exampleBlock = "Your debugging prompts:\n";
      for (const ex of debugExamples.slice(0, 2)) {
        exampleBlock += `  > "${ex}"\n`;
      }
      exampleBlock += "\nLevel up by including:\n";
      exampleBlock += "- The full error message and stack trace\n";
      exampleBlock += "- What you expected vs what happened\n";
      exampleBlock += "- Steps to reproduce";
    }

    recs.push({
      title: "Reduce debugging cycles",
      severity: debugPct > 20 ? "high" : "medium",
      body:
        `${debugPct}% of your prompts are debugging. Reduce this by: ` +
        "1) pasting full error messages + stack traces upfront, " +
        "2) asking Claude to add error handling proactively when building, " +
        "3) requesting defensive coding patterns like input validation.",
      metric: `${debugPct}% debugging | target: <10%`,
      example:
        exampleBlock ||
        "\"Fix the crash in PaymentService.processOrder() — here's the stack " +
          'trace: [paste]. It fails when the cart has items with quantity > 99."',
    });
  }

  // 4. Testing
  if (testPct < 5) {
    recs.push({
      title: "Ask for tests alongside features",
      severity: "medium",
      body:
        `Only ${testPct}% of prompts mention testing. ` +
        "Bundling test requests with feature work catches regressions early " +
        "and forces Claude to think about edge cases during implementation. " +
        "This is one of Claude's strongest capabilities — use it.",
      metric: `${testPct}% testing | recommended: 10-15%`,
      example:
        '"Implement the user search endpoint and write tests covering: ' +
        "empty query, special characters, pagination boundaries, and a " +
        'user with no matching results."',
    });
  }

  // 5. Questions
  if (qPct < 8) {
    recs.push({
      title: "Use Claude as a thinking partner first",
      severity: "medium",
      body:
        `Only ${qPct}% of your prompts are questions. ` +
        "Before diving into implementation, spend 30 seconds asking Claude " +
        "to explain tradeoffs, review your approach, or suggest architecture. " +
        "A quick question prevents expensive wrong turns.",
      metric: `${qPct}% questions | consider: 10-15%`,
      example:
        '"Before I implement caching, walk me through the tradeoffs between ' +
        "Redis and in-memory for our case. We have ~1000 req/min and data " +
        'changes every 5 minutes. What would you recommend?"',
    });
  }

  // 6. Refactoring
  if (refPct < 3) {
    recs.push({
      title: "Schedule refactoring passes",
      severity: "low",
      body:
        `Only ${refPct}% of prompts involve refactoring. ` +
        "After features ship, ask Claude to clean up. It excels at " +
        "mechanical refactoring — extracting shared utils, simplifying " +
        "complex functions, improving naming, reducing duplication.",
      metric: `${refPct}% refactoring | healthy: 5-10%`,
      example:
        '"Review src/api/ for duplicated logic across endpoints. ' +
        "Extract shared patterns into middleware or utility functions. " +
        "Don't change behavior, just clean up the structure.\"",
    });
  }

  // ──────────────────────────────────────────────
  // SESSION & WORKFLOW RECOMMENDATIONS
  // ──────────────────────────────────────────────

  // 7. Batching
  const avgMsgs = summary.total_user_msgs / Math.max(summary.total_sessions, 1);
  if (avgMsgs > 100) {
    recs.push({
      title: "Batch related changes into single prompts",
      severity: "medium",
      body:
        `You average ${avgMsgs.toFixed(0)} messages per session. ` +
        "Try combining related changes: instead of 5 separate prompts " +
        "for 5 files, list all changes in one. Claude handles multi-file " +
        "changes well and produces more coherent diffs.",
      metric: `${avgMsgs.toFixed(0)} msgs/session avg`,
      example:
        '"Rename userService to authService across the codebase: ' +
        "1) rename the file, 2) update all imports, " +
        '3) update tests, 4) update config references."',
    });
  }

  // 8. CLAUDE.md
  if (confirmPct > 10 || microPct > 15) {
    recs.push({
      title: "Use CLAUDE.md for persistent context",
      severity: "low",
      body:
        "Put project conventions, file structure, and recurring instructions " +
        "in a CLAUDE.md file in your project root. Claude reads it at session " +
        "start, so you never have to repeat setup instructions. This single " +
        "file can eliminate dozens of wasted prompts per session.",
      metric: `${summary.total_sessions} sessions could each save setup prompts`,
      example:
        "# CLAUDE.md\n" +
        "- React Native app using Expo + TypeScript strict\n" +
        "- Run tests: npx jest --watchAll=false\n" +
        "- Always use functional components with hooks\n" +
        "- API config in src/config/api.ts\n" +
        "- Don't ask before running tests or fixing lint",
    });
  }

  // ──────────────────────────────────────────────
  // MODEL & COST RECOMMENDATIONS
  // ──────────────────────────────────────────────

  // 9. Model selection
  if (modelList.length > 0) {
    const opusModel = modelList.find((m) => m.display === "Opus");
    const totalCost = summary.estimated_cost || 0;

    if (opusModel && totalCost > 0) {
      const opusPct = Math.round((opusModel.estimated_cost / totalCost) * 100);
      if (opusPct > 70) {
        recs.push({
          title: "Use lighter models for routine tasks",
          severity: opusPct > 85 ? "high" : "medium",
          body:
            `Opus accounts for ${opusPct}% of your estimated API cost. ` +
            "For routine tasks like file searches, simple edits, code formatting, " +
            "and grep operations, Sonnet or Haiku are 5-20x cheaper and just as " +
            "effective. Reserve Opus for complex reasoning and architecture.",
          metric: `Opus: ${opusPct}% of spend | Haiku is 19x cheaper per token`,
          example:
            "Use Claude Code's model selection:\n" +
            "- /model haiku  → quick lookups, file searches, simple fixes\n" +
            "- /model sonnet → standard coding, refactoring, tests\n" +
            "- /model opus   → complex architecture, debugging hard issues",
        });
      }
    }
  }

  // ──────────────────────────────────────────────
  // SUBAGENT & TOOL RECOMMENDATIONS
  // ──────────────────────────────────────────────

  // 10. Subagent usage
  const saCount = sa.total_count || 0;
  const saTypes = sa.type_counts || {};
  const exploreCount = saTypes["Explore"] || 0;
  const gpCount = saTypes["general-purpose"] || 0;

  if (saCount > 0) {
    if (gpCount > exploreCount && gpCount > 20) {
      recs.push({
        title: "Prefer Explore agents over general-purpose",
        severity: "medium",
        body:
          `You spawned ${gpCount} general-purpose agents vs ${exploreCount} Explore agents. ` +
          "Explore agents use Haiku (much cheaper) and are optimized for " +
          "code search, file discovery, and quick lookups. Use general-purpose " +
          "only when the subagent needs to write code or make complex decisions.",
        metric: `${gpCount} general-purpose | ${exploreCount} Explore agents`,
        example:
          "Claude automatically picks agent types, but you can influence it:\n" +
          "- 'find all files that import UserService' → Explore agent\n" +
          "- 'search for how auth is implemented' → Explore agent\n" +
          "- 'refactor the auth module' → general-purpose agent",
      });
    } else if (saCount < 10 && summary.total_sessions > 20) {
      recs.push({
        title: "Let Claude use subagents for parallel work",
        severity: "low",
        body:
          `You've only spawned ${saCount} subagents across ${summary.total_sessions} sessions. ` +
          "Subagents let Claude search code, explore files, and run tasks in " +
          "parallel. For complex tasks, explicitly ask Claude to 'search in parallel' " +
          "or 'explore multiple approaches' to unlock this.",
        metric: `${saCount} subagents across ${summary.total_sessions} sessions`,
        example:
          '"Find all API endpoints that don\'t have authentication middleware ' +
          "and search for any tests that cover unauthenticated access — do both " +
          'searches in parallel."',
      });
    }
  }

  // 11. Compaction events
  const compactionCount = sa.compaction_count || 0;
  if (compactionCount > 3) {
    recs.push({
      title: "Start fresh sessions more often",
      severity: compactionCount > 10 ? "high" : "medium",
      body:
        `Your sessions triggered ${compactionCount} context compactions — ` +
        "meaning Claude's context window filled up and had to be summarized. " +
        "After compaction, Claude loses nuance from earlier in the conversation. " +
        "Start new sessions when switching tasks or after major milestones.",
      metric: `${compactionCount} compactions | each loses context detail`,
      example:
        "Good session boundaries:\n" +
        "- After completing a feature → new session for the next one\n" +
        "- After a successful deploy → new session for bug fixes\n" +
        "- When switching projects → always start fresh",
    });
  }

  // 12. Context efficiency
  const toolPct = ce.tool_pct || 0;
  if (toolPct > 85) {
    recs.push({
      title: "Reduce context window bloat from tool output",
      severity: "medium",
      body:
        `${toolPct}% of Claude's output goes to tool results (file reads, ` +
        "command output, search results). This fills the context window fast. " +
        "Use targeted file reads (specific line ranges), limit grep results, " +
        "and ask Claude to search for specific patterns rather than reading entire files.",
      metric: `${toolPct}% tool output | ${ce.conversation_pct || 0}% conversation`,
      example:
        "Instead of: 'read the entire auth module'\n" +
        "Try: 'read the handleLogin function in src/auth/login.ts (around line 45-80)'\n\n" +
        "Instead of: 'search for all uses of UserContext'\n" +
        "Try: 'find where UserContext.Provider is rendered (should be in App.tsx)'",
    });
  }

  // 13. Thinking blocks
  const thinking = ce.thinking_blocks || 0;
  if (thinking > 0 && total > 0) {
    const thinkingPerSession = thinking / Math.max(summary.total_sessions, 1);
    if (thinkingPerSession > 15) {
      recs.push({
        title: "Extended thinking is being used heavily",
        severity: "low",
        body:
          `Claude used extended thinking ${thinking} times across your sessions ` +
          `(~${thinkingPerSession.toFixed(0)}/session). This is great for complex problems ` +
          "but uses more tokens. For simple tasks, you can nudge Claude to act " +
          "directly: 'just do it, no need to overthink this.'",
        metric: `${thinking} thinking blocks | ${thinkingPerSession.toFixed(0)}/session`,
        example:
          "Thinking is valuable for:\n" +
          "- Debugging complex race conditions\n" +
          "- Designing system architecture\n" +
          "- Multi-file refactoring plans\n\n" +
          "Skip it for: simple renames, formatting, straightforward edits",
      });
    }
  }

  // 14. MCP/skill usage
  if (skillList.length > 0) {
    if (skillList.length < 3) {
      recs.push({
        title: "Explore more MCP integrations",
        severity: "low",
        body:
          `You're using ${skillList.length} MCP tool(s). Claude Code supports ` +
          "integrations with Linear, GitHub, Sentry, Figma, Slack, and many more. " +
          "MCP tools let Claude take actions directly in your tools — creating " +
          "tickets, fetching error reports, reading designs — without leaving the terminal.",
        metric: `${skillList.length} MCP integrations active`,
        example:
          "Popular MCP integrations:\n" +
          "- Linear: create/update tickets from code context\n" +
          "- Sentry: fetch error details for debugging\n" +
          "- Figma: read designs for implementation\n" +
          "- GitHub: manage PRs and issues",
      });
    }
  }

  // ──────────────────────────────────────────────
  // BORIS CHERNY BEST PRACTICES
  // ──────────────────────────────────────────────

  const pm = permissionModes || {};

  // 15. Verification feedback loop
  if (buildPct > 10 && testPct < 5) {
    recs.push({
      title: "Give Claude a way to verify its work",
      severity: "high",
      body:
        `You're building ${buildPct}% of the time but only testing ${testPct}%. ` +
        "The single most impactful Claude Code habit: give it a feedback loop. " +
        "When Claude can run tests after every change, output quality jumps 2-3x. " +
        "Add test commands to CLAUDE.md so Claude runs them automatically.",
      metric: `${buildPct}% building | ${testPct}% testing | recommended: test every change`,
      example:
        "Add to CLAUDE.md:\n" +
        "- After ANY code change, run: npm test -- --related\n" +
        "- After UI changes, run: npx playwright test\n" +
        "- Before committing, run: npm run lint && npm run typecheck\n\n" +
        "Or use a PostToolUse hook in .claude/settings.json to auto-format/test.",
    });
  }

  // 16. Permission mode
  const defaultPct = pm["default"] || 0;
  const autoPct = pm["auto"] || 0;
  const totalPm = Object.values(pm).reduce((s, v) => s + v, 0) || 1;
  if (defaultPct / totalPm > 0.5) {
    recs.push({
      title: "Use /permissions instead of clicking allow",
      severity: "medium",
      body:
        `${((defaultPct / totalPm) * 100).toFixed(0)}% of your messages are in default permission mode. ` +
        "You're likely clicking 'allow' repeatedly for safe commands. Use /permissions " +
        "to pre-approve safe commands (git, npm test, lint) and check them into " +
        ".claude/settings.json to share with your team.",
      metric: `${((defaultPct / totalPm) * 100).toFixed(0)}% default mode | consider: acceptEdits or custom permissions`,
      example:
        "In .claude/settings.json:\n" +
        '{"permissions": {"allow": [\n' +
        '  "Bash(npm test*)", "Bash(npm run lint*)",\n' +
        '  "Bash(git status*)", "Bash(git diff*)",\n' +
        '  "Read", "Glob", "Grep"\n' +
        "]}}\n\n" +
        "Safer than --dangerously-skip-permissions, shared via git.",
    });
  }

  // 17. Hooks for formatting
  const formatPrompts = promptList.filter((p) =>
    ["lint", "format", "prettier", "eslint", "formatting"].some((w) =>
      p.text.toLowerCase().includes(w)
    )
  );
  if (formatPrompts.length > 5) {
    recs.push({
      title: "Use a PostToolUse hook for auto-formatting",
      severity: "medium",
      body:
        `You have ${formatPrompts.length} prompts about formatting/linting. ` +
        "Set up a PostToolUse hook to auto-format code after Claude edits it. " +
        "Claude generates well-formatted code 90% of the time — the hook handles " +
        "the last 10% so you never waste prompts on formatting issues.",
      metric: `${formatPrompts.length} format-related prompts | target: 0 (automated)`,
      example:
        "In .claude/settings.json:\n" +
        '{"hooks": {"PostToolUse": [{\n' +
        '  "matcher": "Edit|Write",\n' +
        '  "command": "npx prettier --write $FILE_PATH"\n' +
        "}]}}\n\n" +
        "Now every file Claude touches is auto-formatted.",
    });
  }

  // 18. Long sessions
  const longSessions = (workDays || []).filter((s) => (s.active_hrs || 0) > 4);
  if (longSessions.length > 3) {
    recs.push({
      title: "Use background agents for long tasks",
      severity: "low",
      body:
        `You have ${longSessions.length} sessions over 4 hours. For long-running ` +
        "tasks, ask Claude to verify its work with a background agent when done, " +
        "or use an AgentStop hook to run validation automatically. This catches " +
        "drift and regressions in marathon sessions.",
      metric: `${longSessions.length} sessions > 4h active time`,
      example:
        "At the end of a long feature task, say:\n" +
        '"Before you finish, run the full test suite and verify all TypeScript ' +
        'types still compile. If anything fails, fix it."\n\n' +
        "Or add a Stop hook that runs tests when a session ends.",
    });
  }

  return recs;
}

// ============================================================
// Main entry point
// ============================================================

export function generateRecommendations(
  data: ParsedData,
  useApi = true
): RecommendationResult {
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

  // In the TypeScript port we only support heuristic analysis (no AI API call)
  for (const r of heuristicRecs) {
    r.rec_source = "heuristic";
  }
  return { recommendations: heuristicRecs, source: "heuristic" };
}

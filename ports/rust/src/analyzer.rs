use serde_json::Value;

fn find_example_prompts(prompts: &[Value], category: &str, max_count: usize, max_len: usize) -> Vec<String> {
    let mut matches: Vec<&Value> = prompts.iter()
        .filter(|p| {
            p.get("category").and_then(|v| v.as_str()) == Some(category)
                && p.get("text").and_then(|v| v.as_str()).map(|t| t.len() > 15).unwrap_or(false)
        })
        .collect();
    matches.sort_by_key(|p| p.get("full_length").and_then(|v| v.as_i64()).unwrap_or(0));
    matches.iter()
        .take(max_count)
        .filter_map(|p| p.get("text").and_then(|v| v.as_str()))
        .map(|t| if t.len() > max_len { t[..max_len].to_string() } else { t.to_string() })
        .collect()
}

fn find_short_prompts(prompts: &[Value], max_chars: i64, max_count: usize) -> Vec<String> {
    let short: Vec<&Value> = prompts.iter()
        .filter(|p| {
            let full_len = p.get("full_length").and_then(|v| v.as_i64()).unwrap_or(0);
            let text = p.get("text").and_then(|v| v.as_str()).unwrap_or("");
            full_len < max_chars && text.trim().len() > 3
        })
        .collect();

    let result: Vec<&Value> = if short.len() > max_count {
        let step = short.len() / max_count;
        (0..max_count).map(|i| short[i * step]).collect()
    } else {
        short
    };

    result.iter()
        .filter_map(|p| p.get("text").and_then(|v| v.as_str()))
        .map(|t| if t.len() > 80 { t[..80].to_string() } else { t.to_string() })
        .collect()
}

pub fn get_heuristic_recommendations(data: &Value) -> Vec<Value> {
    let analysis = &data["analysis"];
    let summary = &data["dashboard"]["summary"];
    let work_days = data.get("work_days").and_then(|v| v.as_array());
    let prompts: Vec<Value> = data.get("prompts").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let models: Vec<Value> = data.get("models").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let subagents = data.get("subagents").cloned().unwrap_or(Value::Object(Default::default()));
    let context_efficiency = data.get("context_efficiency").cloned().unwrap_or(Value::Object(Default::default()));
    let branches: Vec<Value> = data.get("branches").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let skills: Vec<Value> = data.get("skills").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let permission_modes = data.get("permission_modes").cloned().unwrap_or(Value::Object(Default::default()));

    let mut recs: Vec<Value> = Vec::new();
    let total = analysis["total_prompts"].as_i64().unwrap_or(0);
    let avg_len = analysis["avg_length"].as_i64().unwrap_or(0);

    // Build category and length bucket maps
    let categories = analysis["categories"].as_array();
    let length_buckets = analysis["length_buckets"].as_array();

    let get_cat_pct = |name: &str| -> f64 {
        categories.and_then(|cats| {
            cats.iter().find(|c| c["cat"].as_str() == Some(name))
                .and_then(|c| c["pct"].as_f64())
        }).unwrap_or(0.0)
    };

    let get_lb_pct = |name: &str| -> f64 {
        length_buckets.and_then(|lbs| {
            lbs.iter().find(|l| l["bucket"].as_str() == Some(name))
                .and_then(|l| l["pct"].as_f64())
        }).unwrap_or(0.0)
    };

    let micro_pct = get_lb_pct("micro (<20)");
    let short_pct = get_lb_pct("short (20-50)");
    let debug_pct = get_cat_pct("debugging");
    let test_pct = get_cat_pct("testing");
    let ref_pct = get_cat_pct("refactoring");
    let q_pct = get_cat_pct("question");
    let build_pct = get_cat_pct("building");
    let confirm_pct = get_cat_pct("confirmation");
    let _edit_pct = get_cat_pct("editing");

    // 1. Prompt specificity
    if micro_pct + short_pct > 25.0 {
        let short_examples = find_short_prompts(&prompts, 50, 5);
        let mut example_block = String::new();
        if !short_examples.is_empty() {
            example_block.push_str("Your short prompts include:\n");
            for ex in short_examples.iter().take(3) {
                example_block.push_str(&format!("  > \"{}\"\n", ex));
            }
            example_block.push_str("\nTry instead:\n");
            example_block.push_str(
                "\"Fix the login form in src/auth/LoginForm.tsx — it shows a blank \
                 screen after submitting valid credentials. The handleSubmit callback \
                 should redirect to /dashboard but router.push isn't firing.\""
            );
        }

        let (body_text, severity) = if avg_len > 200 {
            (format!(
                "{:.0}% of your prompts are under 50 characters \
                 (though your avg is {} chars — a bimodal pattern). \
                 Those short prompts are often confirmations or follow-ups that \
                 force extra round-trips. Try batching context into fewer, richer prompts.",
                micro_pct + short_pct, avg_len
            ), "medium")
        } else {
            (format!(
                "{:.0}% of your prompts are under 50 characters. \
                 Short prompts force Claude to guess, burning tokens on clarification. \
                 Include: file path, expected vs actual behavior, and constraints. \
                 A specific 100-char prompt saves 5 rounds of back-and-forth.",
                micro_pct + short_pct
            ), "high")
        };

        let example = if example_block.is_empty() {
            "Instead of \"fix the bug\", try:\n\
             \"Fix the login form in src/auth/LoginForm.tsx — blank screen after \
             submit. handleSubmit should redirect to /dashboard.\"".to_string()
        } else {
            example_block
        };

        recs.push(serde_json::json!({
            "title": "Front-load context in your prompts",
            "severity": severity,
            "body": body_text,
            "metric": format!("your avg: {} chars | {:.0}% under 50 chars", avg_len, micro_pct + short_pct),
            "example": example,
        }));
    }

    // 2. High confirmation ratio
    if confirm_pct > 15.0 {
        let confirm_examples = find_example_prompts(&prompts, "confirmation", 3, 150);
        let mut example_block = String::new();
        if !confirm_examples.is_empty() {
            example_block.push_str("Your confirmation prompts include:\n");
            for ex in confirm_examples.iter().take(3) {
                example_block.push_str(&format!("  > \"{}\"\n", ex));
            }
            example_block.push_str("\nEliminate these by adding to CLAUDE.md:\n");
            example_block.push_str(
                "- Auto-fix lint errors without asking\n\
                 - Run tests after every code change\n\
                 - Commit with descriptive messages, don't ask for approval"
            );
        }

        let example = if example_block.is_empty() {
            "Add to CLAUDE.md:\n\
             - Auto-fix lint errors without asking\n\
             - Run tests after every code change\n\
             - Commit with descriptive messages, don't ask for approval".to_string()
        } else {
            example_block
        };

        recs.push(serde_json::json!({
            "title": "Reduce confirmation ping-pong",
            "severity": "medium",
            "body": format!(
                "{}% of your prompts are confirmations (yes, ok, go ahead, etc). \
                 This suggests Claude is asking for permission too often. Set up a \
                 CLAUDE.md with your conventions so Claude can act autonomously, and \
                 use permission mode flags to reduce approval prompts.",
                confirm_pct
            ),
            "metric": format!("{}% confirmations | target: <10%", confirm_pct),
            "example": example,
        }));
    }

    // 3. Debug ratio
    if debug_pct > 12.0 {
        let debug_examples = find_example_prompts(&prompts, "debugging", 3, 150);
        let mut example_block = String::new();
        if !debug_examples.is_empty() {
            example_block.push_str("Your debugging prompts:\n");
            for ex in debug_examples.iter().take(2) {
                example_block.push_str(&format!("  > \"{}\"\n", ex));
            }
            example_block.push_str("\nLevel up by including:\n");
            example_block.push_str("- The full error message and stack trace\n");
            example_block.push_str("- What you expected vs what happened\n");
            example_block.push_str("- Steps to reproduce");
        }

        let severity = if debug_pct > 20.0 { "high" } else { "medium" };
        let example = if example_block.is_empty() {
            "\"Fix the crash in PaymentService.processOrder() — here's the stack \
             trace: [paste]. It fails when the cart has items with quantity > 99.\"".to_string()
        } else {
            example_block
        };

        recs.push(serde_json::json!({
            "title": "Reduce debugging cycles",
            "severity": severity,
            "body": format!(
                "{}% of your prompts are debugging. Reduce this by: \
                 1) pasting full error messages + stack traces upfront, \
                 2) asking Claude to add error handling proactively when building, \
                 3) requesting defensive coding patterns like input validation.",
                debug_pct
            ),
            "metric": format!("{}% debugging | target: <10%", debug_pct),
            "example": example,
        }));
    }

    // 4. Testing
    if test_pct < 5.0 {
        recs.push(serde_json::json!({
            "title": "Ask for tests alongside features",
            "severity": "medium",
            "body": format!(
                "Only {}% of prompts mention testing. \
                 Bundling test requests with feature work catches regressions early \
                 and forces Claude to think about edge cases during implementation. \
                 This is one of Claude's strongest capabilities — use it.",
                test_pct
            ),
            "metric": format!("{}% testing | recommended: 10-15%", test_pct),
            "example": "\"Implement the user search endpoint and write tests covering: \
                         empty query, special characters, pagination boundaries, and a \
                         user with no matching results.\"",
        }));
    }

    // 5. Questions
    if q_pct < 8.0 {
        recs.push(serde_json::json!({
            "title": "Use Claude as a thinking partner first",
            "severity": "medium",
            "body": format!(
                "Only {}% of your prompts are questions. \
                 Before diving into implementation, spend 30 seconds asking Claude \
                 to explain tradeoffs, review your approach, or suggest architecture. \
                 A quick question prevents expensive wrong turns.",
                q_pct
            ),
            "metric": format!("{}% questions | consider: 10-15%", q_pct),
            "example": "\"Before I implement caching, walk me through the tradeoffs between \
                         Redis and in-memory for our case. We have ~1000 req/min and data \
                         changes every 5 minutes. What would you recommend?\"",
        }));
    }

    // 6. Refactoring
    if ref_pct < 3.0 {
        recs.push(serde_json::json!({
            "title": "Schedule refactoring passes",
            "severity": "low",
            "body": format!(
                "Only {}% of prompts involve refactoring. \
                 After features ship, ask Claude to clean up. It excels at \
                 mechanical refactoring — extracting shared utils, simplifying \
                 complex functions, improving naming, reducing duplication.",
                ref_pct
            ),
            "metric": format!("{}% refactoring | healthy: 5-10%", ref_pct),
            "example": "\"Review src/api/ for duplicated logic across endpoints. \
                         Extract shared patterns into middleware or utility functions. \
                         Don't change behavior, just clean up the structure.\"",
        }));
    }

    // 7. Batching
    let total_sessions = summary["total_sessions"].as_i64().unwrap_or(1).max(1);
    let total_user_msgs = summary["total_user_msgs"].as_i64().unwrap_or(0);
    let avg_msgs = total_user_msgs as f64 / total_sessions as f64;
    if avg_msgs > 100.0 {
        recs.push(serde_json::json!({
            "title": "Batch related changes into single prompts",
            "severity": "medium",
            "body": format!(
                "You average {:.0} messages per session. \
                 Try combining related changes: instead of 5 separate prompts \
                 for 5 files, list all changes in one. Claude handles multi-file \
                 changes well and produces more coherent diffs.",
                avg_msgs
            ),
            "metric": format!("{:.0} msgs/session avg", avg_msgs),
            "example": "\"Rename userService to authService across the codebase: \
                         1) rename the file, 2) update all imports, \
                         3) update tests, 4) update config references.\"",
        }));
    }

    // 8. CLAUDE.md
    if confirm_pct > 10.0 || micro_pct > 15.0 {
        recs.push(serde_json::json!({
            "title": "Use CLAUDE.md for persistent context",
            "severity": "low",
            "body": "Put project conventions, file structure, and recurring instructions \
                     in a CLAUDE.md file in your project root. Claude reads it at session \
                     start, so you never have to repeat setup instructions. This single \
                     file can eliminate dozens of wasted prompts per session.",
            "metric": format!("{} sessions could each save setup prompts", total_sessions),
            "example": "# CLAUDE.md\n\
                         - React Native app using Expo + TypeScript strict\n\
                         - Run tests: npx jest --watchAll=false\n\
                         - Always use functional components with hooks\n\
                         - API config in src/config/api.ts\n\
                         - Don't ask before running tests or fixing lint",
        }));
    }

    // 9. Model selection
    if !models.is_empty() {
        let opus_model = models.iter().find(|m| m["display"].as_str() == Some("Opus"));
        let total_cost = summary.get("estimated_cost").and_then(|v| v.as_f64()).unwrap_or(0.0);

        if let Some(opus) = opus_model {
            if total_cost > 0.0 {
                let opus_cost = opus["estimated_cost"].as_f64().unwrap_or(0.0);
                let opus_pct = (opus_cost / total_cost * 100.0).round() as i64;
                if opus_pct > 70 {
                    let severity = if opus_pct > 85 { "high" } else { "medium" };
                    recs.push(serde_json::json!({
                        "title": "Use lighter models for routine tasks",
                        "severity": severity,
                        "body": format!(
                            "Opus accounts for {}% of your estimated API cost. \
                             For routine tasks like file searches, simple edits, code formatting, \
                             and grep operations, Sonnet or Haiku are 5-20x cheaper and just as \
                             effective. Reserve Opus for complex reasoning and architecture.",
                            opus_pct
                        ),
                        "metric": format!("Opus: {}% of spend | Haiku is 19x cheaper per token", opus_pct),
                        "example": "Use Claude Code's model selection:\n\
                                    - /model haiku  → quick lookups, file searches, simple fixes\n\
                                    - /model sonnet → standard coding, refactoring, tests\n\
                                    - /model opus   → complex architecture, debugging hard issues",
                    }));
                }
            }
        }
    }

    // 10. Subagent usage
    let sa_count = subagents.get("total_count").and_then(|v| v.as_i64()).unwrap_or(0);
    let sa_types = subagents.get("type_counts").and_then(|v| v.as_object());
    let explore_count = sa_types.and_then(|t| t.get("Explore")).and_then(|v| v.as_i64()).unwrap_or(0);
    let gp_count = sa_types.and_then(|t| t.get("general-purpose")).and_then(|v| v.as_i64()).unwrap_or(0);

    if sa_count > 0 {
        if gp_count > explore_count && gp_count > 20 {
            recs.push(serde_json::json!({
                "title": "Prefer Explore agents over general-purpose",
                "severity": "medium",
                "body": format!(
                    "You spawned {} general-purpose agents vs {} Explore agents. \
                     Explore agents use Haiku (much cheaper) and are optimized for \
                     code search, file discovery, and quick lookups. Use general-purpose \
                     only when the subagent needs to write code or make complex decisions.",
                    gp_count, explore_count
                ),
                "metric": format!("{} general-purpose | {} Explore agents", gp_count, explore_count),
                "example": "Claude automatically picks agent types, but you can influence it:\n\
                             - 'find all files that import UserService' → Explore agent\n\
                             - 'search for how auth is implemented' → Explore agent\n\
                             - 'refactor the auth module' → general-purpose agent",
            }));
        } else if sa_count < 10 && total_sessions > 20 {
            recs.push(serde_json::json!({
                "title": "Let Claude use subagents for parallel work",
                "severity": "low",
                "body": format!(
                    "You've only spawned {} subagents across {} sessions. \
                     Subagents let Claude search code, explore files, and run tasks in \
                     parallel. For complex tasks, explicitly ask Claude to 'search in parallel' \
                     or 'explore multiple approaches' to unlock this.",
                    sa_count, total_sessions
                ),
                "metric": format!("{} subagents across {} sessions", sa_count, total_sessions),
                "example": "\"Find all API endpoints that don't have authentication middleware \
                             and search for any tests that cover unauthenticated access — do both \
                             searches in parallel.\"",
            }));
        }
    }

    // 11. Compaction events
    let compaction_count = subagents.get("compaction_count").and_then(|v| v.as_i64()).unwrap_or(0);
    if compaction_count > 3 {
        let severity = if compaction_count > 10 { "high" } else { "medium" };
        recs.push(serde_json::json!({
            "title": "Start fresh sessions more often",
            "severity": severity,
            "body": format!(
                "Your sessions triggered {} context compactions — \
                 meaning Claude's context window filled up and had to be summarized. \
                 After compaction, Claude loses nuance from earlier in the conversation. \
                 Start new sessions when switching tasks or after major milestones.",
                compaction_count
            ),
            "metric": format!("{} compactions | each loses context detail", compaction_count),
            "example": "Good session boundaries:\n\
                         - After completing a feature → new session for the next one\n\
                         - After a successful deploy → new session for bug fixes\n\
                         - When switching projects → always start fresh",
        }));
    }

    // 12. Context efficiency
    let tool_pct = context_efficiency.get("tool_pct").and_then(|v| v.as_f64()).unwrap_or(0.0);
    if tool_pct > 85.0 {
        let conversation_pct = context_efficiency.get("conversation_pct").and_then(|v| v.as_f64()).unwrap_or(0.0);
        recs.push(serde_json::json!({
            "title": "Reduce context window bloat from tool output",
            "severity": "medium",
            "body": format!(
                "{}% of Claude's output goes to tool results (file reads, \
                 command output, search results). This fills the context window fast. \
                 Use targeted file reads (specific line ranges), limit grep results, \
                 and ask Claude to search for specific patterns rather than reading entire files.",
                tool_pct
            ),
            "metric": format!("{}% tool output | {}% conversation", tool_pct, conversation_pct),
            "example": "Instead of: 'read the entire auth module'\n\
                         Try: 'read the handleLogin function in src/auth/login.ts (around line 45-80)'\n\n\
                         Instead of: 'search for all uses of UserContext'\n\
                         Try: 'find where UserContext.Provider is rendered (should be in App.tsx)'",
        }));
    }

    // 13. Thinking blocks
    let thinking = context_efficiency.get("thinking_blocks").and_then(|v| v.as_i64()).unwrap_or(0);
    if thinking > 0 && total > 0 {
        let thinking_per_session = thinking as f64 / total_sessions.max(1) as f64;
        if thinking_per_session > 15.0 {
            recs.push(serde_json::json!({
                "title": "Extended thinking is being used heavily",
                "severity": "low",
                "body": format!(
                    "Claude used extended thinking {} times across your sessions \
                     (~{:.0}/session). This is great for complex problems \
                     but uses more tokens. For simple tasks, you can nudge Claude to act \
                     directly: 'just do it, no need to overthink this.'",
                    thinking, thinking_per_session
                ),
                "metric": format!("{} thinking blocks | {:.0}/session", thinking, thinking_per_session),
                "example": "Thinking is valuable for:\n\
                             - Debugging complex race conditions\n\
                             - Designing system architecture\n\
                             - Multi-file refactoring plans\n\n\
                             Skip it for: simple renames, formatting, straightforward edits",
            }));
        }
    }

    // 14. MCP/skill usage
    if !skills.is_empty() {
        let skill_count = skills.len();
        if skill_count < 3 {
            recs.push(serde_json::json!({
                "title": "Explore more MCP integrations",
                "severity": "low",
                "body": format!(
                    "You're using {} MCP tool(s). Claude Code supports \
                     integrations with Linear, GitHub, Sentry, Figma, Slack, and many more. \
                     MCP tools let Claude take actions directly in your tools — creating \
                     tickets, fetching error reports, reading designs — without leaving the terminal.",
                    skill_count
                ),
                "metric": format!("{} MCP integrations active", skill_count),
                "example": "Popular MCP integrations:\n\
                             - Linear: create/update tickets from code context\n\
                             - Sentry: fetch error details for debugging\n\
                             - Figma: read designs for implementation\n\
                             - GitHub: manage PRs and issues",
            }));
        }
    }

    // === BORIS CHERNY BEST PRACTICES ===

    // 15. Verification feedback loop
    if build_pct > 10.0 && test_pct < 5.0 {
        recs.push(serde_json::json!({
            "title": "Give Claude a way to verify its work",
            "severity": "high",
            "body": format!(
                "You're building {:.0}% of the time but only testing {:.0}%. \
                 The single most impactful Claude Code habit: give it a feedback loop. \
                 When Claude can run tests after every change, output quality jumps 2-3x. \
                 Add test commands to CLAUDE.md so Claude runs them automatically.",
                build_pct, test_pct
            ),
            "metric": format!("{:.0}% building | {:.0}% testing | recommended: test every change", build_pct, test_pct),
            "example": "Add to CLAUDE.md:\n\
                         - After ANY code change, run: npm test -- --related\n\
                         - After UI changes, run: npx playwright test\n\
                         - Before committing, run: npm run lint && npm run typecheck\n\n\
                         Or use a PostToolUse hook in .claude/settings.json to auto-format/test.",
        }));
    }

    // 16. Permission mode
    let pm_obj = permission_modes.as_object();
    let default_count = pm_obj.and_then(|m| m.get("default")).and_then(|v| v.as_i64()).unwrap_or(0);
    let total_pm: i64 = pm_obj.map(|m| m.values().filter_map(|v| v.as_i64()).sum()).unwrap_or(1).max(1);
    let default_ratio = default_count as f64 / total_pm as f64;

    if default_ratio > 0.5 {
        recs.push(serde_json::json!({
            "title": "Use /permissions instead of clicking allow",
            "severity": "medium",
            "body": format!(
                "{:.0}% of your messages are in default permission mode. \
                 You're likely clicking 'allow' repeatedly for safe commands. Use /permissions \
                 to pre-approve safe commands (git, npm test, lint) and check them into \
                 .claude/settings.json to share with your team.",
                default_ratio * 100.0
            ),
            "metric": format!("{:.0}% default mode | consider: acceptEdits or custom permissions", default_ratio * 100.0),
            "example": "In .claude/settings.json:\n\
                         {\"permissions\": {\"allow\": [\n\
                           \"Bash(npm test*)\", \"Bash(npm run lint*)\",\n\
                           \"Bash(git status*)\", \"Bash(git diff*)\",\n\
                           \"Read\", \"Glob\", \"Grep\"\n\
                         ]}}\n\n\
                         Safer than --dangerously-skip-permissions, shared via git.",
        }));
    }

    // 17. Hooks for formatting
    let format_prompts_count = prompts.iter().filter(|p| {
        let text = p.get("text").and_then(|v| v.as_str()).unwrap_or("").to_lowercase();
        ["lint", "format", "prettier", "eslint", "formatting"].iter().any(|w| text.contains(w))
    }).count();

    if format_prompts_count > 5 {
        recs.push(serde_json::json!({
            "title": "Use a PostToolUse hook for auto-formatting",
            "severity": "medium",
            "body": format!(
                "You have {} prompts about formatting/linting. \
                 Set up a PostToolUse hook to auto-format code after Claude edits it. \
                 Claude generates well-formatted code 90% of the time — the hook handles \
                 the last 10% so you never waste prompts on formatting issues.",
                format_prompts_count
            ),
            "metric": format!("{} format-related prompts | target: 0 (automated)", format_prompts_count),
            "example": "In .claude/settings.json:\n\
                         {\"hooks\": {\"PostToolUse\": [{\n\
                           \"matcher\": \"Edit|Write\",\n\
                           \"command\": \"npx prettier --write $FILE_PATH\"\n\
                         }]}}\n\n\
                         Now every file Claude touches is auto-formatted.",
        }));
    }

    // 18. Long sessions
    if let Some(wd) = work_days {
        let long_sessions: Vec<&Value> = wd.iter()
            .filter(|s| s.get("active_hrs").and_then(|v| v.as_f64()).unwrap_or(0.0) > 4.0)
            .collect();
        if long_sessions.len() > 3 {
            recs.push(serde_json::json!({
                "title": "Use background agents for long tasks",
                "severity": "low",
                "body": format!(
                    "You have {} sessions over 4 hours. For long-running \
                     tasks, ask Claude to verify its work with a background agent when done, \
                     or use an AgentStop hook to run validation automatically. This catches \
                     drift and regressions in marathon sessions.",
                    long_sessions.len()
                ),
                "metric": format!("{} sessions > 4h active time", long_sessions.len()),
                "example": "At the end of a long feature task, say:\n\
                             \"Before you finish, run the full test suite and verify all TypeScript \
                             types still compile. If anything fails, fix it.\"\n\n\
                             Or add a Stop hook that runs tests when a session ends.",
            }));
        }
    }

    recs
}

pub fn generate_recommendations(data: &Value) -> Value {
    let heuristic_recs = get_heuristic_recommendations(data);

    let tagged_recs: Vec<Value> = heuristic_recs.into_iter().map(|mut r| {
        if let Some(obj) = r.as_object_mut() {
            obj.insert("rec_source".to_string(), Value::String("heuristic".to_string()));
        }
        r
    }).collect();

    serde_json::json!({
        "recommendations": tagged_recs,
        "source": "heuristic",
    })
}

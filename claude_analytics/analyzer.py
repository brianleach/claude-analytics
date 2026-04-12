"""AI-powered prompt analysis using Claude API."""

import json
import os
import sys
import random


def find_example_prompts(prompts, category, max_count=3, max_len=150):
    """Find real example prompts from a specific category."""
    matches = [p for p in prompts if p.get("category") == category and len(p.get("text", "")) > 15]
    # Prefer shorter prompts that illustrate the problem
    matches.sort(key=lambda p: p.get("full_length", 0))
    return [p["text"][:max_len] for p in matches[:max_count]]


def find_short_prompts(prompts, max_chars=50, max_count=5):
    """Find real examples of short prompts the user sent."""
    short = [p for p in prompts if p.get("full_length", 0) < max_chars and len(p.get("text", "").strip()) > 3]
    # Pick a diverse sample
    if len(short) > max_count:
        step = len(short) // max_count
        short = [short[i * step] for i in range(max_count)]
    return [p["text"][:80] for p in short]


def get_heuristic_recommendations(analysis, summary, work_days, prompts=None,
                                   models=None, subagents=None, context_efficiency=None,
                                   branches=None, skills=None):
    """Generate recommendations using local heuristics (no API needed).

    Now uses actual prompt examples and expanded data for richer tips.
    """
    recs = []
    total = analysis["total_prompts"]
    avg_len = analysis["avg_length"]
    prompts = prompts or []
    models = models or []
    subagents = subagents or {}
    context_efficiency = context_efficiency or {}
    branches = branches or []
    skills = skills or []

    cat_map = {c["cat"]: c for c in analysis["categories"]}
    lb_map = {l["bucket"]: l for l in analysis["length_buckets"]}

    micro_pct = lb_map.get("micro (<20)", {}).get("pct", 0)
    short_pct = lb_map.get("short (20-50)", {}).get("pct", 0)
    debug_pct = cat_map.get("debugging", {}).get("pct", 0)
    test_pct = cat_map.get("testing", {}).get("pct", 0)
    ref_pct = cat_map.get("refactoring", {}).get("pct", 0)
    q_pct = cat_map.get("question", {}).get("pct", 0)
    build_pct = cat_map.get("building", {}).get("pct", 0)
    confirm_pct = cat_map.get("confirmation", {}).get("pct", 0)
    edit_pct = cat_map.get("editing", {}).get("pct", 0)

    # ──────────────────────────────────────────────
    # PROMPTING RECOMMENDATIONS
    # ──────────────────────────────────────────────

    # 1. Prompt specificity — with real examples
    if micro_pct + short_pct > 25:
        short_examples = find_short_prompts(prompts)
        example_block = ""
        if short_examples:
            example_block = "Your short prompts include:\n"
            for ex in short_examples[:3]:
                example_block += f'  > "{ex}"\n'
            example_block += "\nTry instead:\n"
            example_block += (
                '"Fix the login form in src/auth/LoginForm.tsx — it shows a blank '
                'screen after submitting valid credentials. The handleSubmit callback '
                'should redirect to /dashboard but router.push isn\'t firing."'
            )
        # Acknowledge bimodal distribution when avg is high
        if avg_len > 200:
            body_text = (
                f"{micro_pct + short_pct:.0f}% of your prompts are under 50 characters "
                f"(though your avg is {avg_len} chars — a bimodal pattern). "
                "Those short prompts are often confirmations or follow-ups that "
                "force extra round-trips. Try batching context into fewer, richer prompts."
            )
            severity = "medium"
        else:
            body_text = (
                f"{micro_pct + short_pct:.0f}% of your prompts are under 50 characters. "
                "Short prompts force Claude to guess, burning tokens on clarification. "
                "Include: file path, expected vs actual behavior, and constraints. "
                "A specific 100-char prompt saves 5 rounds of back-and-forth."
            )
            severity = "high"
        recs.append({
            "title": "Front-load context in your prompts",
            "severity": severity,
            "body": body_text,
            "metric": f"your avg: {avg_len} chars | {micro_pct + short_pct:.0f}% under 50 chars",
            "example": example_block or (
                'Instead of "fix the bug", try:\n'
                '"Fix the login form in src/auth/LoginForm.tsx — blank screen after '
                'submit. handleSubmit should redirect to /dashboard."'
            ),
        })

    # 2. High confirmation ratio — you're just saying "yes" a lot
    if confirm_pct > 15:
        confirm_examples = find_example_prompts(prompts, "confirmation")
        recs.append({
            "title": "Reduce confirmation ping-pong",
            "severity": "medium",
            "body": (
                f"{confirm_pct}% of your prompts are confirmations (yes, ok, go ahead, etc). "
                "This suggests Claude is asking for permission too often. Set up a "
                "CLAUDE.md with your conventions so Claude can act autonomously, and "
                "use permission mode flags to reduce approval prompts."
            ),
            "metric": f"{confirm_pct}% confirmations | target: <10%",
            "example": (
                "Add to CLAUDE.md:\n"
                "- Auto-fix lint errors without asking\n"
                "- Run tests after every code change\n"
                "- Commit with descriptive messages, don't ask for approval"
            ),
        })

    # 3. Debug ratio — with real debugging prompts
    if debug_pct > 12:
        debug_examples = find_example_prompts(prompts, "debugging")
        example_block = ""
        if debug_examples:
            example_block = "Your debugging prompts:\n"
            for ex in debug_examples[:2]:
                example_block += f'  > "{ex}"\n'
            example_block += "\nLevel up by including:\n"
            example_block += "- The full error message and stack trace\n"
            example_block += "- What you expected vs what happened\n"
            example_block += "- Steps to reproduce"
        recs.append({
            "title": "Reduce debugging cycles",
            "severity": "high" if debug_pct > 20 else "medium",
            "body": (
                f"{debug_pct}% of your prompts are debugging. Reduce this by: "
                "1) pasting full error messages + stack traces upfront, "
                "2) asking Claude to add error handling proactively when building, "
                "3) requesting defensive coding patterns like input validation."
            ),
            "metric": f"{debug_pct}% debugging | target: <10%",
            "example": example_block or (
                '"Fix the crash in PaymentService.processOrder() — here\'s the stack '
                'trace: [paste]. It fails when the cart has items with quantity > 99."'
            ),
        })

    # 4. Testing
    if test_pct < 5:
        recs.append({
            "title": "Ask for tests alongside features",
            "severity": "medium",
            "body": (
                f"Only {test_pct}% of prompts mention testing. "
                "Bundling test requests with feature work catches regressions early "
                "and forces Claude to think about edge cases during implementation. "
                "This is one of Claude's strongest capabilities — use it."
            ),
            "metric": f"{test_pct}% testing | recommended: 10-15%",
            "example": (
                '"Implement the user search endpoint and write tests covering: '
                'empty query, special characters, pagination boundaries, and a '
                'user with no matching results."'
            ),
        })

    # 5. Questions — thinking before building
    if q_pct < 8:
        recs.append({
            "title": "Use Claude as a thinking partner first",
            "severity": "medium",
            "body": (
                f"Only {q_pct}% of your prompts are questions. "
                "Before diving into implementation, spend 30 seconds asking Claude "
                "to explain tradeoffs, review your approach, or suggest architecture. "
                "A quick question prevents expensive wrong turns."
            ),
            "metric": f"{q_pct}% questions | consider: 10-15%",
            "example": (
                '"Before I implement caching, walk me through the tradeoffs between '
                'Redis and in-memory for our case. We have ~1000 req/min and data '
                'changes every 5 minutes. What would you recommend?"'
            ),
        })

    # 6. Refactoring
    if ref_pct < 3:
        recs.append({
            "title": "Schedule refactoring passes",
            "severity": "low",
            "body": (
                f"Only {ref_pct}% of prompts involve refactoring. "
                "After features ship, ask Claude to clean up. It excels at "
                "mechanical refactoring — extracting shared utils, simplifying "
                "complex functions, improving naming, reducing duplication."
            ),
            "metric": f"{ref_pct}% refactoring | healthy: 5-10%",
            "example": (
                '"Review src/api/ for duplicated logic across endpoints. '
                'Extract shared patterns into middleware or utility functions. '
                'Don\'t change behavior, just clean up the structure."'
            ),
        })

    # ──────────────────────────────────────────────
    # SESSION & WORKFLOW RECOMMENDATIONS
    # ──────────────────────────────────────────────

    # 7. Batching (high messages per session)
    avg_msgs = summary["total_user_msgs"] / max(summary["total_sessions"], 1)
    if avg_msgs > 100:
        recs.append({
            "title": "Batch related changes into single prompts",
            "severity": "medium",
            "body": (
                f"You average {avg_msgs:.0f} messages per session. "
                "Try combining related changes: instead of 5 separate prompts "
                "for 5 files, list all changes in one. Claude handles multi-file "
                "changes well and produces more coherent diffs."
            ),
            "metric": f"{avg_msgs:.0f} msgs/session avg",
            "example": (
                '"Rename userService to authService across the codebase: '
                '1) rename the file, 2) update all imports, '
                '3) update tests, 4) update config references."'
            ),
        })

    # 8. CLAUDE.md — only suggest if confirmation rate is high (suggests repeated setup)
    if confirm_pct > 10 or micro_pct > 15:
        recs.append({
            "title": "Use CLAUDE.md for persistent context",
            "severity": "low",
            "body": (
                "Put project conventions, file structure, and recurring instructions "
                "in a CLAUDE.md file in your project root. Claude reads it at session "
                "start, so you never have to repeat setup instructions. This single "
                "file can eliminate dozens of wasted prompts per session."
            ),
            "metric": f"{summary['total_sessions']} sessions could each save setup prompts",
            "example": (
                "# CLAUDE.md\n"
                "- React Native app using Expo + TypeScript strict\n"
                "- Run tests: npx jest --watchAll=false\n"
                "- Always use functional components with hooks\n"
                "- API config in src/config/api.ts\n"
                "- Don't ask before running tests or fixing lint"
            ),
        })

    # ──────────────────────────────────────────────
    # MODEL & COST RECOMMENDATIONS
    # ──────────────────────────────────────────────

    # 9. Model selection
    if models:
        opus_model = next((m for m in models if m["display"] == "Opus"), None)
        haiku_model = next((m for m in models if m["display"] == "Haiku"), None)
        total_cost = summary.get("estimated_cost", 0)

        if opus_model and total_cost > 0:
            opus_pct = round(opus_model["estimated_cost"] / total_cost * 100)
            if opus_pct > 70:
                recs.append({
                    "title": "Use lighter models for routine tasks",
                    "severity": "high" if opus_pct > 85 else "medium",
                    "body": (
                        f"Opus accounts for {opus_pct}% of your estimated API cost. "
                        "For routine tasks like file searches, simple edits, code formatting, "
                        "and grep operations, Sonnet or Haiku are 5-20x cheaper and just as "
                        "effective. Reserve Opus for complex reasoning and architecture."
                    ),
                    "metric": f"Opus: {opus_pct}% of spend | Haiku is 19x cheaper per token",
                    "example": (
                        "Use Claude Code's model selection:\n"
                        "- /model haiku  → quick lookups, file searches, simple fixes\n"
                        "- /model sonnet → standard coding, refactoring, tests\n"
                        "- /model opus   → complex architecture, debugging hard issues"
                    ),
                })

    # ──────────────────────────────────────────────
    # SUBAGENT & TOOL RECOMMENDATIONS
    # ──────────────────────────────────────────────

    # 10. Subagent usage
    sa_count = subagents.get("total_count", 0)
    sa_types = subagents.get("type_counts", {})
    explore_count = sa_types.get("Explore", 0)
    gp_count = sa_types.get("general-purpose", 0)

    if sa_count > 0:
        if gp_count > explore_count and gp_count > 20:
            recs.append({
                "title": "Prefer Explore agents over general-purpose",
                "severity": "medium",
                "body": (
                    f"You spawned {gp_count} general-purpose agents vs {explore_count} Explore agents. "
                    "Explore agents use Haiku (much cheaper) and are optimized for "
                    "code search, file discovery, and quick lookups. Use general-purpose "
                    "only when the subagent needs to write code or make complex decisions."
                ),
                "metric": f"{gp_count} general-purpose | {explore_count} Explore agents",
                "example": (
                    "Claude automatically picks agent types, but you can influence it:\n"
                    "- 'find all files that import UserService' → Explore agent\n"
                    "- 'search for how auth is implemented' → Explore agent\n"
                    "- 'refactor the auth module' → general-purpose agent"
                ),
            })
        elif sa_count < 10 and summary["total_sessions"] > 20:
            recs.append({
                "title": "Let Claude use subagents for parallel work",
                "severity": "low",
                "body": (
                    f"You've only spawned {sa_count} subagents across {summary['total_sessions']} sessions. "
                    "Subagents let Claude search code, explore files, and run tasks in "
                    "parallel. For complex tasks, explicitly ask Claude to 'search in parallel' "
                    "or 'explore multiple approaches' to unlock this."
                ),
                "metric": f"{sa_count} subagents across {summary['total_sessions']} sessions",
                "example": (
                    '"Find all API endpoints that don\'t have authentication middleware '
                    'and search for any tests that cover unauthenticated access — do both '
                    'searches in parallel."'
                ),
            })

    # 11. Compaction events
    compaction_count = subagents.get("compaction_count", 0)
    if compaction_count > 3:
        recs.append({
            "title": "Start fresh sessions more often",
            "severity": "high" if compaction_count > 10 else "medium",
            "body": (
                f"Your sessions triggered {compaction_count} context compactions — "
                "meaning Claude's context window filled up and had to be summarized. "
                "After compaction, Claude loses nuance from earlier in the conversation. "
                "Start new sessions when switching tasks or after major milestones."
            ),
            "metric": f"{compaction_count} compactions | each loses context detail",
            "example": (
                "Good session boundaries:\n"
                "- After completing a feature → new session for the next one\n"
                "- After a successful deploy → new session for bug fixes\n"
                "- When switching projects → always start fresh"
            ),
        })

    # 12. Context efficiency
    tool_pct = context_efficiency.get("tool_pct", 0)
    if tool_pct > 85:
        recs.append({
            "title": "Reduce context window bloat from tool output",
            "severity": "medium",
            "body": (
                f"{tool_pct}% of Claude's output goes to tool results (file reads, "
                "command output, search results). This fills the context window fast. "
                "Use targeted file reads (specific line ranges), limit grep results, "
                "and ask Claude to search for specific patterns rather than reading entire files."
            ),
            "metric": f"{tool_pct}% tool output | {context_efficiency.get('conversation_pct', 0)}% conversation",
            "example": (
                "Instead of: 'read the entire auth module'\n"
                "Try: 'read the handleLogin function in src/auth/login.ts (around line 45-80)'\n\n"
                "Instead of: 'search for all uses of UserContext'\n"
                "Try: 'find where UserContext.Provider is rendered (should be in App.tsx)'"
            ),
        })

    # 13. Thinking blocks
    thinking = context_efficiency.get("thinking_blocks", 0)
    if thinking > 0 and total > 0:
        thinking_per_session = thinking / max(summary["total_sessions"], 1)
        if thinking_per_session > 15:
            recs.append({
                "title": "Extended thinking is being used heavily",
                "severity": "low",
                "body": (
                    f"Claude used extended thinking {thinking} times across your sessions "
                    f"(~{thinking_per_session:.0f}/session). This is great for complex problems "
                    "but uses more tokens. For simple tasks, you can nudge Claude to act "
                    "directly: 'just do it, no need to overthink this.'"
                ),
                "metric": f"{thinking} thinking blocks | {thinking_per_session:.0f}/session",
                "example": (
                    "Thinking is valuable for:\n"
                    "- Debugging complex race conditions\n"
                    "- Designing system architecture\n"
                    "- Multi-file refactoring plans\n\n"
                    "Skip it for: simple renames, formatting, straightforward edits"
                ),
            })

    # 14. MCP/skill usage
    if skills:
        top_skill = skills[0]["skill"] if skills else None
        skill_count = len(skills)
        if skill_count < 3:
            recs.append({
                "title": "Explore more MCP integrations",
                "severity": "low",
                "body": (
                    f"You're using {skill_count} MCP tool(s). Claude Code supports "
                    "integrations with Linear, GitHub, Sentry, Figma, Slack, and many more. "
                    "MCP tools let Claude take actions directly in your tools — creating "
                    "tickets, fetching error reports, reading designs — without leaving the terminal."
                ),
                "metric": f"{skill_count} MCP integrations active",
                "example": (
                    "Popular MCP integrations:\n"
                    "- Linear: create/update tickets from code context\n"
                    "- Sentry: fetch error details for debugging\n"
                    "- Figma: read designs for implementation\n"
                    "- GitHub: manage PRs and issues"
                ),
            })

    return recs


def get_ai_recommendations(analysis, summary, prompts_sample, work_days,
                            models=None, subagents=None, context_efficiency=None,
                            branches=None, skills=None):
    """Generate recommendations using Claude API for deeper, personalized analysis."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY not set"

    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed (pip install anthropic)"

    client = anthropic.Anthropic(api_key=api_key)

    # === Build rich context ===
    cat_summary = ", ".join(
        f"{c['cat']}: {c['pct']}%" for c in analysis["categories"][:8]
    )
    len_summary = ", ".join(
        f"{l['bucket']}: {l['pct']}%" for l in analysis["length_buckets"]
    )

    # Sample prompts by category (real examples)
    sample_by_cat = {}
    for p in prompts_sample:
        cat = p["category"]
        if cat not in sample_by_cat:
            sample_by_cat[cat] = []
        if len(sample_by_cat[cat]) < 5:
            sample_by_cat[cat].append({
                "text": p["text"][:300],
                "length": p.get("full_length", len(p["text"])),
                "project": p.get("project", ""),
            })

    sample_text = ""
    for cat, samples in sorted(sample_by_cat.items(), key=lambda x: -len(x[1])):
        sample_text += f"\n### {cat} ({len(samples)} samples)\n"
        for s in samples:
            sample_text += f'  [{s["project"]}] ({s["length"]}ch) "{s["text"]}"\n'

    # Work pattern
    work_summary = "No work pattern data"
    if work_days:
        total_active = sum(d["active_hrs"] for d in work_days)
        avg_daily = total_active / len(work_days)
        avg_prompts = sum(d["prompts"] for d in work_days) / len(work_days)
        work_summary = (
            f"Active days: {len(work_days)}, avg active hours/day: {avg_daily:.1f}h, "
            f"avg prompts/day: {avg_prompts:.0f}, total active hours: {total_active:.1f}h"
        )

    # Model usage
    model_text = "No model data"
    if models:
        model_text = "\n".join(
            f"  {m['display']}: {m['msgs']} msgs, ${m['estimated_cost']:.2f} estimated cost"
            for m in models if m["msgs"] > 0
        )

    # Subagent usage
    sa_text = "No subagent data"
    if subagents and subagents.get("total_count", 0) > 0:
        sa = subagents
        sa_text = (
            f"Total: {sa['total_count']}, Compactions: {sa['compaction_count']}\n"
            f"  Types: {json.dumps(sa.get('type_counts', {}))}\n"
            f"  Subagent cost: ${sa.get('estimated_cost', 0):.2f}"
        )

    # Context efficiency
    ce_text = "No context data"
    if context_efficiency:
        ce = context_efficiency
        ce_text = (
            f"Tool output: {ce.get('tool_pct', 0)}%, Conversation: {ce.get('conversation_pct', 0)}%, "
            f"Thinking blocks: {ce.get('thinking_blocks', 0)}, "
            f"Subagent output share: {ce.get('subagent_pct', 0)}%"
        )

    # Branch summary
    branch_text = "No branch data"
    if branches:
        branch_text = "\n".join(
            f"  {b['branch']}: {b['msgs']} msgs, {b['sessions']} sessions"
            for b in branches[:10]
        )

    prompt = f"""You are an expert Claude Code productivity coach. Analyze this developer's usage patterns and provide specific, actionable recommendations to help them get more out of Claude Code.

Be direct, specific, and reference their actual data. Don't be generic — every recommendation should cite a specific number, pattern, or example from their usage. Think of this as a personalized coaching session.

## Usage Overview
- Total prompts: {analysis['total_prompts']} across {summary['total_sessions']} sessions, {summary['unique_projects']} projects
- Date range: {summary['date_range_start']} to {summary['date_range_end']}
- Average prompt length: {analysis['avg_length']} chars
- Estimated total API cost: ${summary.get('estimated_cost', 0):.2f}
- {work_summary}

## Prompt Categories
{cat_summary}

## Prompt Length Distribution
{len_summary}

## Model Usage
{model_text}

## Subagent Usage
{sa_text}

## Context Window Efficiency
{ce_text}

## Git Branch Activity
{branch_text}

## Project Quality Scores
{json.dumps(analysis['project_quality'][:8], indent=2)}

## Sample Prompts (real examples from this user)
{sample_text}

## Instructions

Provide 7-10 recommendations as a JSON array. Each recommendation:
- "title": short, punchy, actionable (imperative mood, max 8 words)
- "severity": "high", "medium", or "low"
- "body": 2-4 sentences. Reference their SPECIFIC numbers and patterns. Explain the WHY and the IMPACT.
- "metric": one-line with their current number vs target/benchmark
- "example": a CONCRETE example. If critiquing their prompts, show a real prompt they used and how to improve it. Use before/after format where possible.

Priority order:
1. HIGH: Things costing them significant time or money right now
2. MEDIUM: Workflow improvements that compound over time
3. LOW: Nice-to-have optimizations

Cover these areas (skip any that don't apply):
- Prompt quality and specificity (cite their actual short/vague prompts)
- Model selection strategy (are they using Opus for everything?)
- Subagent and parallel work patterns
- Testing and defensive coding habits
- Session management (compactions, session length)
- Context window efficiency
- MCP tool and integration usage

Return ONLY valid JSON array, no markdown fences or commentary."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("["):
            recs = json.loads(text)
        else:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                recs = json.loads(text[start:end])
            else:
                return None, "Could not parse API response as JSON"
        return recs, None
    except Exception as e:
        return None, str(e)


def generate_recommendations(data, use_api=True):
    """Generate recommendations, trying API first then falling back to heuristics.

    Returns:
        dict with 'recommendations' list and 'source' ('ai' or 'heuristic')
    """
    analysis = data["analysis"]
    summary = data["dashboard"]["summary"]
    work_days = data.get("work_days", [])
    prompts = data.get("prompts", [])
    models = data.get("models", [])
    subagents = data.get("subagents", {})
    context_efficiency = data.get("context_efficiency", {})
    branches = data.get("branches", [])
    skills = data.get("skills", [])

    # Always generate heuristic recs as fallback
    heuristic_recs = get_heuristic_recommendations(
        analysis, summary, work_days, prompts,
        models, subagents, context_efficiency, branches, skills
    )

    if not use_api:
        print("  Using heuristic analysis (--no-api)")
        return {"recommendations": heuristic_recs, "source": "heuristic"}

    print("  Generating AI-powered recommendations...")
    ai_recs, error = get_ai_recommendations(
        analysis, summary, prompts[:80], work_days,
        models, subagents, context_efficiency, branches, skills
    )

    if ai_recs:
        print(f"  AI recommendations generated ({len(ai_recs)} tips)")
        return {"recommendations": ai_recs, "source": "ai"}
    else:
        print(f"  AI analysis unavailable ({error}), using heuristic analysis")
        return {"recommendations": heuristic_recs, "source": "heuristic"}

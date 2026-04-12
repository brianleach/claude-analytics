# I Built a Tool That Analyzes How You Use Claude Code — Here's What I Learned About My Own Habits

I've been using Claude Code daily for the past few weeks across 17 projects. I wanted to know: am I actually using it well? So I built claude-analytics — an open-source CLI that parses your local Claude Code session data and generates an interactive HTML report with personalized recommendations.

Here's what it found when I turned it on myself.

## The Tool

claude-analytics reads the JSONL session files that Claude Code stores in ~/.claude/projects/. It parses every message, tool call, token count, model selection, subagent spawn, and git branch — then generates a self-contained HTML dashboard with a retro terminal aesthetic.

The report has three layers:

**Dashboard** — Your rank badge (scored across 20 criteria), daily activity chart, weekly rhythm heatmap, and clickable work day cards that drill down into individual prompts.

**Deep Dive** — Cost estimation with per-model breakdown, model usage doughnut charts, subagent analysis, git branch correlation, MCP integration tracking, and configuration audit.

**Charts** — 11 prompt analysis and trend charts covering categories, length distribution, project quality scores, hourly patterns, session lengths, and week-over-week trends.

## The Recommendations Engine

This is where it gets interesting. The tool runs two recommendation systems:

**AI-powered (Claude Opus)** — Sends a summary of your usage patterns to Claude with a prompt engineered to be blunt and specific. It quotes your actual prompts and rewrites them better. It cites dollar amounts. It tells you which Claude Code features you're not using.

**Pattern-based** — Heuristic rules that detect anti-patterns from the data: high debugging ratio, missing tests, excessive confirmations, underused subagents, missing PostToolUse hooks, and more. These are inspired by tips from Boris Cherny (the creator of Claude Code) about how power users get the most out of the tool.

Both run every time. AI tips get an "AI generated" badge, pattern tips get "pattern match." No confusion about what came from where.

## What I Learned About My Usage

**85/100 — Grand Master rank.** But the gaps were revealing:

- **24% of my prompts were debugging.** That's more than double the recommended ceiling. The tool showed me my actual debugging prompts — vague things like "fix before merging" — and rewrote them with specific file paths, expected behavior, and constraints.

- **Only 1.9% of my prompts mentioned testing.** The single most impactful Claude Code habit according to Boris Cherny: give Claude a way to verify its work. If it can run tests after every change, output quality jumps 2-3x. I wasn't doing this.

- **99.8% of my messages used Opus.** For everything. Git status checks. Simple file reads. Grep operations. The tool estimated I could cut costs significantly by switching to Sonnet for routine tasks with /model sonnet.

- **Zero PostToolUse hooks configured.** Claude generates well-formatted code 90% of the time. A simple hook to run prettier after every edit handles the last 10% automatically — eliminating an entire category of back-and-forth.

- **13.8% micro prompts** — "yes", "y", "go ahead". Each one burns a full context window reload at Opus pricing for a trivial response. Batching confirmations into richer follow-up prompts saves both time and tokens.

## How It's Built

Four Python files, one HTML template, ~2,900 lines total:

- **parser.py** — Reads JSONL sessions, extracts messages, tracks models/tokens/costs/subagents/branches/permissions
- **analyzer.py** — Dual recommendation engine (Opus API + heuristic rules), threaded spinner during API calls
- **generator.py** — Injects data into the HTML template, manages timestamped output with .gitignore protection
- **template.html** — Self-contained dashboard with Chart.js, lazy-rendered tabs, drill-down drawers

Everything runs locally. Your prompts never leave your machine unless you opt into AI recommendations, which sends up to 80 prompt excerpts (truncated to 300 chars) to the Anthropic API.

The output folder is double-gitignored so you can't accidentally commit your session data to a public repo.

## The Interesting Technical Bits

**Subagent parsing** — Claude Code spawns subagents for parallel work (Explore agents for code search, general-purpose for complex tasks). The tool reads both JSONL files and .meta.json sidecars to identify types, track compaction events, and calculate per-subagent cost.

**Prompt categorization with word boundaries** — Early versions used substring matching ("fix" in text), which meant "prefix" triggered the debugging category. The fix: regex word boundary matching with \b anchors.

**Cost estimation** — Per-model pricing (Opus/Sonnet/Haiku) with cache read and cache write token tracking. Important: this is raw API cost, not subscription cost. The report makes this distinction clear with disclaimers and a separate Deep Dive section.

**Rank scoring** — 20 binary criteria across four dimensions (prompt quality, tool sophistication, session maturity, efficiency). Simple, transparent, gamified. Grand Master requires hitting 16+ of 20 signals.

## Try It

```bash
git clone https://github.com/brianleach/claude-analytics.git
cd claude-analytics
pip install -e ".[ai]"
claude-analytics
```

Takes about a second to parse your data, ~45 seconds if you have an API key for the AI recommendations. Opens an interactive report in your browser.

The repo: github.com/brianleach/claude-analytics

What does your rank look like? What patterns does it find in your usage?

---

Built with Claude Code. Analyzed by Claude Code. The snake eating its own tail.

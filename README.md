# claude-analytics

Analyze your [Claude Code](https://docs.anthropic.com/en/docs/claude-code) usage and get personalized recommendations to level up your prompting.

Parses your local `~/.claude/` session data, generates an interactive dashboard, and uses AI to coach you on writing better prompts.

![Terminal retro dashboard](https://img.shields.io/badge/style-terminal_retro-33ff88?style=flat-square&labelColor=0a0a0a) ![Python 3.8+](https://img.shields.io/badge/python-3.8+-44ddff?style=flat-square&labelColor=0a0a0a) ![License MIT](https://img.shields.io/badge/license-MIT-ffaa33?style=flat-square&labelColor=0a0a0a)

## What You Get

**A recommendations engine**, not just charts. The report leads with actionable coaching based on your actual prompt patterns, then backs it up with usage data.

- **AI-powered recommendations** — Claude analyzes your prompts and suggests specific improvements with example prompts you can copy
- **Prompt quality analysis** — breakdown by category (debugging, building, testing, etc.), length distribution, and per-project quality scores
- **Working hours estimate** — daily active hours, span, and weekly totals
- **Interactive charts** — daily activity, weekly heatmap, project breakdown, tool usage, session lengths, and more
- **Multi-level drill-down** — click a chart → see sessions → click a session → read individual prompts with timestamps and categories

Everything runs locally. Your prompts never leave your machine (unless you opt into AI recommendations, which sends a small sample to the Anthropic API).

## Quick Start

```bash
# Clone the repo
git clone https://github.com/brianleach/claude-analytics.git
cd claude-analytics

# Install
pip install -e .

# Run (auto-opens in browser)
claude-analytics
```

That's it. The report generates from your local `~/.claude/` data and opens in your browser.

## AI-Powered Recommendations

For deeper analysis, set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
claude-analytics
```

If you use Claude Code, you likely already have this key in your shell environment. The AI analysis sends a small summary of your usage patterns (not your full prompts) to generate personalized coaching.

To skip AI and use only local heuristic analysis:

```bash
claude-analytics --no-api
```

## Options

```
claude-analytics [OPTIONS]

  --no-api          Skip AI analysis, use heuristics only
  --no-open         Don't auto-open the report in the browser
  -o, --output      Output path (default: ./claude-analytics-report.html)
  --claude-dir      Path to .claude directory (default: ~/.claude)
  --tz-offset       Timezone offset from UTC in hours (auto-detected)
  --version         Show version
```

## Requirements

- Python 3.8+
- Claude Code installed and used (needs `~/.claude/projects/` data)
- `anthropic` Python package (for AI recommendations, optional)

## How It Works

1. **Parse** — reads JSONL session files from `~/.claude/projects/`, extracts messages, timestamps, tool usage, and token counts
2. **Analyze** — categorizes your prompts (debugging, building, testing, etc.), measures prompt quality, calculates working patterns
3. **Recommend** — generates personalized tips using Claude API (or local heuristics), referencing your specific numbers
4. **Render** — injects everything into an interactive HTML dashboard and opens it in your browser

All processing happens locally. The generated HTML is a single self-contained file with no external dependencies (Chart.js is loaded from CDN).

## What Gets Analyzed

From your `~/.claude/` directory:

- **Session metadata** — timestamps, durations, project directories
- **Your prompts** — categorized by intent (building, debugging, testing, etc.) and measured by length/specificity
- **Claude's responses** — tool usage, models used, token counts
- **Work patterns** — active hours, daily rhythm, weekly trends

Nothing is uploaded or shared. The AI recommendation feature sends only aggregated statistics and a small sample of prompt text to the Anthropic API.

## License

MIT

# claude-analytics

A CLI tool that parses your local `~/.claude/` session data and generates an interactive HTML report with personalized recommendations. It combines AI-powered analysis (via Claude Opus) with pattern-based heuristics to help you write better prompts and understand your Claude Code usage.

![Terminal retro dashboard](https://img.shields.io/badge/style-terminal_retro-33ff88?style=flat-square&labelColor=0a0a0a) ![Python 3.8+](https://img.shields.io/badge/python-3.8+-44ddff?style=flat-square&labelColor=0a0a0a) ![License MIT](https://img.shields.io/badge/license-MIT-ffaa33?style=flat-square&labelColor=0a0a0a)

## What You Get

**A recommendations engine**, not just charts. The report leads with actionable coaching based on your actual prompt patterns, then backs it up with detailed usage data.

- **AI-powered recommendations** -- Claude Opus analyzes up to 80 prompt excerpts and generates specific, personalized coaching with copy-ready example prompts
- **Pattern-based recommendations** -- heuristic analysis runs alongside (or instead of) AI, detecting short prompts, missing context, debugging patterns, and more
- **Cost estimation** -- per-model breakdown (Opus, Sonnet, Haiku) with cache read/write tracking and reduction tips
- **Model usage** -- clickable doughnut charts showing model distribution across sessions
- **Subagent analysis** -- subagent types, compaction events, and context window efficiency metrics
- **Git branch correlation** -- session activity mapped to branches and projects
- **Skill and slash command tracking** -- frequency and usage patterns for Claude Code skills
- **MCP integration usage** -- which MCP tools are being called and how often
- **Permission mode tracking** -- breakdown of permission modes used across sessions
- **Working hours estimate** -- daily active hours, span, and weekly totals with clickable day cards
- **11 prompt analysis and trend charts** -- daily activity, weekly heatmap, category breakdown, length distribution, per-project quality scores, and more (lazy-rendered for performance)
- **Interactive drill-down** -- click a chart to see sessions, click a session to read individual prompts with timestamps and categories
- **Boris Cherny best practices detection** -- checks for hooks, verification patterns, and permission configuration

Everything runs locally. Your prompts never leave your machine unless you opt into AI recommendations (see Privacy & Security below).

## Quick Start

```bash
# Clone the repo
git clone https://github.com/brianleach/claude-analytics.git
cd claude-analytics

# Install (basic -- no external dependencies)
pip install -e .

# Install with AI recommendations support
pip install -e ".[ai]"

# Run (auto-opens in browser)
claude-analytics
```

That's it. The report generates from your local `~/.claude/` data and opens in your browser.

## Configuration

For AI-powered recommendations, set your Anthropic API key. You can either export it directly:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or create a `.env` file in the project directory (see `.env.example`):

```
ANTHROPIC_API_KEY=sk-ant-...
```

If you already use Claude Code, the key is likely in your shell environment.

## CLI Options

```
claude-analytics [OPTIONS]

  --no-api          Skip AI analysis, use pattern-based heuristics only
  --no-open         Don't auto-open the report in the browser
  -o, --output      Output path (default: ./output/claude-analytics-TIMESTAMP.html)
  --claude-dir      Path to .claude directory (default: ~/.claude)
  --tz-offset       Timezone offset from UTC in hours (auto-detected)
  --since DATE      Only include data since DATE (YYYY-MM-DD), or 'last' for since last run
  --version         Show version
```

The CLI runs in five steps:

```
[1/5] Locating Claude data...
[2/5] Parsing sessions...
[3/5] Analyzing prompt patterns...
[4/5] Generating AI-powered recommendations (Claude Opus)...
[5/5] Generating report...
```

## Privacy & Security

- **Stays local**: all parsing, analysis, chart rendering, and heuristic recommendations run entirely on your machine
- **AI recommendations (opt-in)**: when enabled, sends up to 80 prompt excerpts (each truncated to 300 characters) plus aggregated usage statistics to the Anthropic API -- no full prompts or file contents are sent
- **Output is double-gitignored**: the `output/` directory and legacy `claude-analytics-report.html` path are both listed in `.gitignore` to prevent accidental commits of reports containing your prompt data
- **No telemetry**: nothing is uploaded, tracked, or shared beyond the optional API call above

## How It Works

1. **Parse** -- reads JSONL session files from `~/.claude/projects/`, extracts messages, timestamps, tool usage, token counts, model info, subagent data, and MCP calls
2. **Analyze** -- categorizes prompts (debugging, building, testing, etc.), measures prompt quality, calculates working patterns, detects best practices
3. **Recommend** -- generates personalized tips using a dual system: Claude Opus API for deep analysis (optional) and pattern-based heuristics that always run, referencing your specific numbers and real prompt examples
4. **Render** -- injects everything into a self-contained interactive HTML dashboard with lazy-rendered charts and opens it in your browser

## Requirements

- Python 3.8+
- Claude Code installed and used (needs `~/.claude/projects/` data)
- `anthropic` Python package (optional, for AI recommendations -- install with `pip install -e ".[ai]"`)

## License

MIT

# claude-analytics

A CLI tool that parses your local `~/.claude/` session data and generates an interactive HTML report with personalized recommendations to help you get more out of Claude Code.

Combines AI-powered analysis (Claude Opus) with pattern-based heuristics to coach you on prompt quality, model selection, workflow efficiency, and Claude Code features you might be missing.

![TypeScript](https://img.shields.io/badge/typescript-5.0+-44ddff?style=flat-square&labelColor=0a0a0a) ![Python 3.8+](https://img.shields.io/badge/python-3.8+-44ddff?style=flat-square&labelColor=0a0a0a) ![Go 1.21+](https://img.shields.io/badge/go-1.21+-44ddff?style=flat-square&labelColor=0a0a0a) ![Rust 1.70+](https://img.shields.io/badge/rust-1.70+-44ddff?style=flat-square&labelColor=0a0a0a) ![License MIT](https://img.shields.io/badge/license-MIT-ffaa33?style=flat-square&labelColor=0a0a0a)

## Quick Start

```bash
git clone https://github.com/brianleach/claude-analytics.git
cd claude-analytics
make install
```

Add your Anthropic API key for the best results (AI-powered recommendations via Claude Opus, ~$0.15-0.25 per run):

```bash
cp .env.example .env
# Edit .env and add your key (get one at https://console.anthropic.com/)
```

Then run:

```bash
make run                  # TypeScript (fastest, default)
make run PORT=python      # Python
make run PORT=go          # Go
make run PORT=rust        # Rust
```

That's it. The report generates from your `~/.claude/` data and opens in your browser. If no API key is set, it still works — you'll get pattern-based recommendations instead of AI-powered ones.

You can also run without the API: `make run-no-api`

## Ports

The tool is implemented in four languages. All ports produce the same interactive HTML report with both AI-powered and heuristic recommendations.

```
ports/
  typescript/   ← fastest (0.55s avg)
  rust/         ← compiled, 0.72s avg
  python/       ← 0.82s avg
  go/           ← 1.12s avg
```

### Running each port

All ports support `--no-api`, `--no-open`, `--since`, `--output`, `--claude-dir`, and `--tz-offset`.

**TypeScript** (default, fastest):
```bash
cd ports/typescript
npm install
npx ts-node src/cli.ts
```

**Python**:
```bash
cd ports/python
pip install -e ".[ai]"
claude-analytics
```

**Go**:
```bash
cd ports/go
go build -o claude-analytics .
./claude-analytics
```
Note: Go uses single-dash flags (`-no-api`, `-no-open`, `-output`, `-claude-dir`).

**Rust**:
```bash
cd ports/rust
cargo build --release
./target/release/claude-analytics
```

### Benchmarks

Run `./benchmark.sh` from the repo root to race all four implementations against your data:

```
TypeScript:  0.55s
Rust:        0.72s
Python:      0.82s
Go:          1.12s
```

All under 1.2 seconds for ~300MB of session data across 360 JSONL files. The AI recommendation step adds ~45 seconds for the Opus API call.

## What You Get

**A recommendations engine**, not just charts. The report leads with actionable coaching based on your actual prompt patterns, then backs it up with detailed usage data.

### Recommendations

- **AI-powered recommendations** -- Claude Opus analyzes your prompt samples and generates specific, personalized coaching with before/after rewrites of your actual prompts
- **Pattern-based recommendations** -- heuristic rules detect anti-patterns: short prompts, excessive debugging, missing tests, underused subagents, missing PostToolUse hooks, and more (inspired by [Boris Cherny's Claude Code tips](https://x.com/bcherny))
- **Both run every time** -- AI tips are labeled "AI generated", pattern tips are labeled "pattern match", displayed in separate sections

### Dashboard

- **Yegge Level badge** -- your level on [Steve Yegge's 8 Levels of Developer-Agent Evolution](https://justin.abrah.ms/blog/2026-01-08-yegge-s-developer-agent-evolution-model.html) (L1 Near-Zero AI through L8 Custom Orchestrator), detected from your usage signals
- **Daily activity chart** -- click bars to drill into sessions for that day
- **Weekly rhythm heatmap** -- spot your peak hours and dead zones
- **Work day cards** -- clickable cards showing active hours, span, and prompt count per day

### Deep Dive

- **Cost estimation** -- per-model breakdown (Opus, Sonnet, Haiku) with cache read/write tracking, cost drivers, and reduction tips
- **Model usage** -- clickable doughnut charts for messages, tokens, and cost by model
- **Subagent analysis** -- types, compaction events, context window efficiency (tool output vs conversation tokens)
- **Git branch correlation** -- session activity mapped to branches
- **Skill tracking** -- slash command and MCP integration usage
- **Permission modes** -- breakdown of auto, acceptEdits, and default modes
- **Configuration audit** -- plugins and feature flags from .claude.json

### Charts

- **11 prompt analysis and trend charts** -- categories, length distribution, per-project quality scores, hourly patterns, session lengths, week-over-week trends, output volume (lazy-rendered)
- **Interactive drill-down** -- click chart -> sessions -> individual prompts with timestamps and categories

## CLI Options

```
claude-analytics [OPTIONS]

  --no-api          Skip AI analysis, use pattern-based heuristics only
  --no-open         Don't auto-open the report in the browser
  -o, --output      Output path (default: ./output/claude-analytics-TIMESTAMP.html)
  --claude-dir      Path to .claude directory (default: ~/.claude)
  --tz-offset       Timezone offset from UTC in hours (auto-detected)
  --since DATE      Only include data since DATE (YYYY-MM-DD), or 'last'
                    for since last run
  --version         Show version
```

## Privacy & Security

- **Local by default**: all parsing, chart rendering, and pattern-based recommendations run entirely on your machine
- **AI recommendations (opt-in)**: sends up to 80 prompt excerpts (each truncated to 300 characters) plus aggregated usage statistics to the Anthropic API. No full prompts, file contents, or code are sent
- **Reports are double-gitignored**: `output/` is in both root `.gitignore` and has its own internal `.gitignore` to prevent accidental commits of session data
- **No telemetry**: nothing is uploaded, tracked, or shared beyond the optional API call

## How It Works

1. **Parse** -- reads JSONL session files from `~/.claude/projects/`, extracts messages, timestamps, tool usage, token counts, model info, subagent data, permission modes, and MCP calls
2. **Analyze** -- categorizes prompts by intent, measures quality, calculates working patterns, detects best practices gaps
3. **Recommend** -- dual system: Claude Opus API generates personalized coaching with real prompt rewrites (optional), pattern-based heuristics always run and detect anti-patterns like missing hooks, low test coverage, and model overuse
4. **Render** -- injects everything into a self-contained HTML dashboard and opens it in your browser

## Author

[Brian Leach](https://www.linkedin.com/in/bleach/) — [I Built a Tool That Tells You If You're Actually Good at Claude Code](https://www.linkedin.com/posts/bleach_activity-7449940726718734336-b2l6)

## License

MIT

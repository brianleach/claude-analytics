#!/usr/bin/env bash
set -e

CLAUDE_DIR="$HOME/.claude"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESULTS=()
TIMES=()

TOTAL_START=$(python3 -c "import time; print(time.time())")

echo ""
echo "=========================================="
echo "  claude-analytics benchmark"
echo "=========================================="
echo ""
echo "Data source: $CLAUDE_DIR"
echo ""

# ── Python ──────────────────────────────────────
echo "── Python ──"
PY_DIR="$SCRIPT_DIR/ports/python"
if [ -f "$PY_DIR/setup.py" ] && command -v python3 &>/dev/null; then
    cd "$PY_DIR"
    if [ -d "$SCRIPT_DIR/.venv" ]; then
        source "$SCRIPT_DIR/.venv/bin/activate" 2>/dev/null || true
    fi
    START=$(python3 -c "import time; print(time.time())")
    python3 -m claude_analytics --no-api --no-open --claude-dir "$CLAUDE_DIR" -o /tmp/bench-python.html 2>&1 | tail -3
    END=$(python3 -c "import time; print(time.time())")
    ELAPSED=$(python3 -c "print(f'{$END - $START:.3f}')")
    echo "  Time: ${ELAPSED}s"
    RESULTS+=("Python")
    TIMES+=("$ELAPSED")
else
    echo "  SKIP: python3 not found"
fi
echo ""

# ── TypeScript ──────────────────────────────────
echo "── TypeScript ──"
TS_DIR="$SCRIPT_DIR/ports/typescript"
if [ -f "$TS_DIR/package.json" ]; then
    cd "$TS_DIR"
    if [ ! -d "node_modules" ]; then
        echo "  Installing deps..."
        npm install --silent 2>&1 | tail -1
    fi
    # Build first (compile TS -> JS)
    if [ -f "tsconfig.json" ]; then
        npx tsc --noEmit false 2>/dev/null || npx tsc 2>/dev/null || true
    fi
    START=$(python3 -c "import time; print(time.time())")
    if [ -f "dist/cli.js" ]; then
        node dist/cli.js --no-api --no-open --claude-dir "$CLAUDE_DIR" -o /tmp/bench-typescript.html 2>&1 | tail -3
    elif [ -f "src/cli.ts" ]; then
        npx ts-node src/cli.ts --no-api --no-open --claude-dir "$CLAUDE_DIR" -o /tmp/bench-typescript.html 2>&1 | tail -3
    else
        echo "  SKIP: no entry point found"
    fi
    END=$(python3 -c "import time; print(time.time())")
    ELAPSED=$(python3 -c "print(f'{$END - $START:.3f}')")
    echo "  Time: ${ELAPSED}s"
    RESULTS+=("TypeScript")
    TIMES+=("$ELAPSED")
else
    echo "  SKIP: no package.json"
fi
echo ""

# ── Go ──────────────────────────────────────────
echo "── Go ──"
GO_DIR="$SCRIPT_DIR/ports/go"
if [ -f "$GO_DIR/go.mod" ]; then
    cd "$GO_DIR"
    if [ ! -f "claude-analytics" ]; then
        echo "  Building..."
        go build -o claude-analytics . 2>&1
    fi
    START=$(python3 -c "import time; print(time.time())")
    ./claude-analytics -no-api -no-open -claude-dir "$CLAUDE_DIR" -output /tmp/bench-go.html 2>&1 | tail -3
    END=$(python3 -c "import time; print(time.time())")
    ELAPSED=$(python3 -c "print(f'{$END - $START:.3f}')")
    echo "  Time: ${ELAPSED}s"
    RESULTS+=("Go")
    TIMES+=("$ELAPSED")
else
    echo "  SKIP: no go.mod"
fi
echo ""

# ── Rust ────────────────────────────────────────
echo "── Rust ──"
RUST_DIR="$SCRIPT_DIR/ports/rust"
if [ -f "$RUST_DIR/Cargo.toml" ]; then
    cd "$RUST_DIR"
    if [ ! -f "target/release/claude-analytics" ]; then
        echo "  Building (release)..."
        cargo build --release 2>&1 | tail -3
    fi
    START=$(python3 -c "import time; print(time.time())")
    ./target/release/claude-analytics --no-api --no-open --claude-dir "$CLAUDE_DIR" -o /tmp/bench-rust.html 2>&1 | tail -3
    END=$(python3 -c "import time; print(time.time())")
    ELAPSED=$(python3 -c "print(f'{$END - $START:.3f}')")
    echo "  Time: ${ELAPSED}s"
    RESULTS+=("Rust")
    TIMES+=("$ELAPSED")
else
    echo "  SKIP: no Cargo.toml"
fi
echo ""

# ── Results ─────────────────────────────────────
echo "=========================================="
echo "  RESULTS"
echo "=========================================="
echo ""

# Sort by time and display
for i in "${!RESULTS[@]}"; do
    echo "  ${RESULTS[$i]}: ${TIMES[$i]}s"
done | sort -t: -k2 -n

echo ""

# Find winner
WINNER=""
BEST="999"
for i in "${!RESULTS[@]}"; do
    COMP=$(python3 -c "print('1' if ${TIMES[$i]} < $BEST else '0')")
    if [ "$COMP" = "1" ]; then
        BEST="${TIMES[$i]}"
        WINNER="${RESULTS[$i]}"
    fi
done

echo "  Winner: $WINNER (${BEST}s)"
echo ""

TOTAL_END=$(python3 -c "import time; print(time.time())")
TOTAL_ELAPSED=$(python3 -c "print(f'{$TOTAL_END - $TOTAL_START:.3f}')")
echo "  Total benchmark time: ${TOTAL_ELAPSED}s"
echo ""

# Compare output sizes
echo "  Output sizes:"
for f in /tmp/bench-*.html; do
    if [ -f "$f" ]; then
        SIZE=$(du -h "$f" | cut -f1)
        NAME=$(basename "$f" .html | sed 's/bench-//')
        echo "    $NAME: $SIZE"
    fi
done
echo ""

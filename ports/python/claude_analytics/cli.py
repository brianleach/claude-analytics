"""CLI entry point for claude-analytics."""

import argparse
import os
import platform
import subprocess
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .parser import find_claude_dir, parse_all_sessions
from .analyzer import generate_recommendations
from .generator import generate_html, write_report, read_last_run, save_last_run


BANNER_LINES = [
    "   ____ _                 _",
    "  / ___| | __ _ _   _  __| | ___",
    " | |   | |/ _` | | | |/ _` |/ _ \\",
    " | |___| | (_| | |_| | (_| |  __/",
    "  \\____|_|\\__,_|\\__,_|\\__,_|\\___|",
    "     _                _       _   _",
    "    / \\   _ __   __ _| |_   _| |_(_) ___ ___",
    "   / _ \\ | '_ \\ / _` | | | | | __| |/ __/ __|",
    "  / ___ \\| | | | (_| | | |_| | |_| | (__\\__ \\",
    " /_/   \\_\\_| |_|\\__,_|_|\\__, |\\__|_|\\___|___/",
    "                         |___/",
]

# Anthropic/Claude orange: \033[38;2;255;149;0m (RGB 255, 149, 0)
ORANGE = "\033[38;2;227;115;34m"
RESET = "\033[0m"
BANNER = "\n" + "\n".join(f"{ORANGE}{line}{RESET}" for line in BANNER_LINES) + "\n"


def open_in_browser(filepath):
    """Open an HTML file in the user's default browser."""
    file_url = f"file://{filepath}"

    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", str(filepath)], check=True)
        elif system == "Windows":
            os.startfile(str(filepath))
        elif system == "Linux":
            subprocess.run(["xdg-open", str(filepath)], check=True)
        else:
            webbrowser.open(file_url)
    except Exception:
        webbrowser.open(file_url)


def main():
    # Load .env if present (for ANTHROPIC_API_KEY)
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val

    parser = argparse.ArgumentParser(
        prog="claude-analytics",
        description="Analyze your Claude Code usage and level up your prompting.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--no-api",
        action="store_true",
        help="Skip AI-powered analysis (no API key needed)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Don't auto-open the report in the browser",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Output path for the HTML report (default: ./output/claude-analytics-TIMESTAMP.html)",
    )
    parser.add_argument(
        "--claude-dir",
        type=str,
        default=None,
        help="Path to .claude directory (default: ~/.claude)",
    )
    parser.add_argument(
        "--tz-offset",
        type=int,
        default=None,
        help="Timezone offset from UTC in hours (auto-detected if not set)",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        help="Only include data since this date (YYYY-MM-DD) or 'last' for since last run",
    )

    args = parser.parse_args()

    print(BANNER)
    print(f"  v{__version__}")
    print()

    # Step 1: Find Claude directory
    print(f"{ORANGE}[1/5]{RESET} Locating Claude data...")
    try:
        if args.claude_dir:
            claude_dir = Path(args.claude_dir)
            if not claude_dir.exists():
                print(f"  Error: {claude_dir} not found")
                sys.exit(1)
        else:
            claude_dir = find_claude_dir()
        print(f"  Found: {claude_dir}")
    except FileNotFoundError as e:
        print(f"  Error: {e}")
        sys.exit(1)

    # Resolve --since flag
    since_date = None
    if args.since:
        if args.since.lower() == "last":
            since_date = read_last_run()
            if since_date:
                print(f"  Filtering to data since last run: {since_date}")
            else:
                print("  No previous run found, showing all data")
        else:
            since_date = args.since
            print(f"  Filtering to data since: {since_date}")

    # Step 2: Parse sessions
    print(f"{ORANGE}[2/5]{RESET} Parsing sessions...")
    try:
        data = parse_all_sessions(claude_dir, tz_offset=args.tz_offset, since_date=since_date)
        summary = data["dashboard"]["summary"]
        print(f"  {summary['total_sessions']} sessions across {summary['unique_projects']} projects")
        print(f"  {summary['total_user_msgs']:,} messages, {data['analysis']['total_prompts']:,} prompts")
        if since_date:
            print(f"  Showing: {since_date} → {summary['date_range_end']}")
        else:
            print(f"  {summary['date_range_start']} → {summary['date_range_end']}")
        print(f"  Timezone: {summary['tz_label']}")
    except (FileNotFoundError, ValueError) as e:
        print(f"  Error: {e}")
        sys.exit(1)

    # Step 3: Heuristic analysis
    print(f"{ORANGE}[3/5]{RESET} Analyzing prompt patterns...")
    use_api = not args.no_api
    if use_api and not os.environ.get("ANTHROPIC_API_KEY"):
        print("  ANTHROPIC_API_KEY not set, using heuristic analysis only")
        print("  (set the key or use --no-api to skip this message)")
        use_api = False

    # Step 4: AI analysis (if key available)
    if use_api:
        print(f"{ORANGE}[4/5]{RESET} Generating AI-powered recommendations (Claude Opus)...")
    else:
        print(f"{ORANGE}[4/5]{RESET} Generating heuristic recommendations...")
    recommendations = generate_recommendations(data, use_api=use_api)
    rec_count = len(recommendations.get("recommendations", []))
    source_label = "AI + heuristic" if recommendations["source"] == "ai" else "heuristic"
    print(f"  {rec_count} recommendations ({source_label})")

    # Step 5: Generate report
    print(f"{ORANGE}[5/5]{RESET} Generating report...")
    html = generate_html(data, recommendations)
    output_path = write_report(html, output_path=args.output)
    print(f"  Report saved to: {output_path}")

    file_size_kb = output_path.stat().st_size / 1024
    print(f"  Size: {file_size_kb:.0f} KB")

    # Save the last-run marker for --since last
    save_last_run()
    print()

    # Open in browser
    if not args.no_open:
        print(f"Opening report in browser...")
        open_in_browser(output_path)
    else:
        print(f"Open the report: file://{output_path}")

    print()
    print("Done! Go level up your Claude game.")


if __name__ == "__main__":
    main()

"""CLI entry point for claude-analytics."""

import argparse
import os
import platform
import subprocess
import sys
import webbrowser
from pathlib import Path

# Load .env if present (for ANTHROPIC_API_KEY)
_env_path = Path.cwd() / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _, _val = _line.partition("=")
                _key = _key.strip()
                _val = _val.strip().strip("'\"")
                if _key and _key not in os.environ:
                    os.environ[_key] = _val

from . import __version__
from .parser import find_claude_dir, parse_all_sessions
from .analyzer import generate_recommendations
from .generator import generate_html, write_report, read_last_run, save_last_run


BANNER = r"""
   _____ _                 _         _                _       _   _
  / ____| |               | |       | |    /\        | |     | | (_)
 | |    | | __ _ _   _  __| | ___   | |   /  \   _ __| | __ _| |_ _  ___ ___
 | |    | |/ _` | | | |/ _` |/ _ \  | |  / /\ \ | '__| |/ _` | __| |/ __/ __|
 | |____| | (_| | |_| | (_| |  __/  | | / ____ \| |  | | (_| | |_| | (__\__ \
  \_____|_|\__,_|\__,_|\__,_|\___|  |_|/_/    \_\_|  |_|\__,_|\__|_|\___|___/
"""


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
    print("[1/4] Locating Claude data...")
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
    print("[2/4] Parsing sessions...")
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

    # Step 3: Generate recommendations
    print("[3/4] Analyzing prompts...")
    use_api = not args.no_api
    if use_api and not os.environ.get("ANTHROPIC_API_KEY"):
        print("  ANTHROPIC_API_KEY not set, using heuristic analysis")
        print("  (set the key or use --no-api to skip this message)")
        use_api = False
    recommendations = generate_recommendations(data, use_api=use_api)
    rec_count = len(recommendations.get("recommendations", []))
    print(f"  Generated {rec_count} recommendations ({recommendations['source']})")

    # Step 4: Generate report
    print("[4/4] Generating report...")
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

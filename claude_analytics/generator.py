"""Generate the HTML dashboard from parsed data."""

import json
import os
from datetime import datetime
from pathlib import Path


def get_template():
    """Load the HTML template from the package directory."""
    template_path = Path(__file__).parent / "template.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found at {template_path}")
    return template_path.read_text(encoding="utf-8")


def generate_html(data, recommendations):
    """Generate the final HTML dashboard.

    Args:
        data: Parsed session data from parser.parse_all_sessions()
        recommendations: Dict from analyzer.generate_recommendations()

    Returns:
        str: Complete HTML content
    """
    template = get_template()

    # Build the payload: everything the template needs
    payload = {
        "dashboard": data["dashboard"],
        "drilldown": data["drilldown"],
        "analysis": data["analysis"],
        "recommendations": recommendations,
        "work_days": data.get("work_days", []),
        # New data
        "models": data.get("models", []),
        "subagents": data.get("subagents", {}),
        "branches": data.get("branches", []),
        "context_efficiency": data.get("context_efficiency", {}),
        "versions": data.get("versions", []),
        "skills": data.get("skills", []),
        "slash_commands": data.get("slash_commands", []),
        "config": data.get("config", {}),
    }

    # Inject data into template
    payload_json = json.dumps(payload, separators=(",", ":"))
    html = template.replace("__DATA_PLACEHOLDER__", payload_json)

    return html


def write_report(html, output_path=None):
    """Write the HTML report to disk.

    Reports are saved to an 'output/' directory with timestamped filenames
    so previous runs are preserved for tracking improvement over time.
    The output/ folder is automatically .gitignored to prevent leaking
    sensitive session data.

    Args:
        html: HTML content string
        output_path: Where to write. Defaults to ./output/claude-analytics-YYYYMMDD-HHMMSS.html

    Returns:
        Path: The output file path
    """
    if output_path is None:
        output_dir = Path.cwd() / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = output_dir / f"claude-analytics-{timestamp}.html"

        # Ensure output/ is gitignored
        _ensure_gitignore(output_dir)
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    return output_path


def read_last_run(output_dir=None):
    """Read the last run timestamp from the .last-run marker file.

    Returns:
        str or None: ISO date string (YYYY-MM-DD) of the last run, or None.
    """
    if output_dir is None:
        output_dir = Path.cwd() / "output"
    marker = output_dir / ".last-run"
    if marker.exists():
        content = marker.read_text(encoding="utf-8").strip()
        # Return just the date portion
        return content[:10] if len(content) >= 10 else None
    return None


def save_last_run(output_dir=None):
    """Save the current timestamp as the last run marker.

    Args:
        output_dir: The output directory. Defaults to ./output/
    """
    if output_dir is None:
        output_dir = Path.cwd() / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    marker = output_dir / ".last-run"
    marker.write_text(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n",
        encoding="utf-8",
    )


def _ensure_gitignore(output_dir):
    """Create or update .gitignore in the output directory.

    Also adds 'output/' to the project root .gitignore if it exists.
    """
    # .gitignore inside output/ — catch-all
    inner_gitignore = output_dir / ".gitignore"
    if not inner_gitignore.exists():
        inner_gitignore.write_text(
            "# Claude Analytics reports contain sensitive session data.\n"
            "# Do NOT commit these files to version control.\n"
            "*\n"
            "!.gitignore\n",
            encoding="utf-8",
        )

    # Also add 'output/' to the project root .gitignore
    root_gitignore = output_dir.parent / ".gitignore"
    if root_gitignore.exists():
        content = root_gitignore.read_text(encoding="utf-8")
        if "output/" not in content:
            with open(root_gitignore, "a", encoding="utf-8") as f:
                f.write("\n# Claude Analytics reports (contain sensitive data)\noutput/\n")
    else:
        root_gitignore.write_text(
            "# Claude Analytics reports (contain sensitive data)\noutput/\n",
            encoding="utf-8",
        )

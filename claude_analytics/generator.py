"""Generate the HTML dashboard from parsed data."""

import json
import os
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
    }

    # Inject data into template
    payload_json = json.dumps(payload, separators=(",", ":"))
    html = template.replace("__DATA_PLACEHOLDER__", payload_json)

    return html


def write_report(html, output_path=None):
    """Write the HTML report to disk.

    Args:
        html: HTML content string
        output_path: Where to write. Defaults to ./claude-analytics-report.html

    Returns:
        Path: The output file path
    """
    if output_path is None:
        output_path = Path.cwd() / "claude-analytics-report.html"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    return output_path

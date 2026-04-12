"""AI-powered prompt analysis using Claude API."""

import json
import os
import sys


def get_heuristic_recommendations(analysis, summary, work_days):
    """Generate recommendations using local heuristics (no API needed)."""
    recs = []
    total = analysis["total_prompts"]
    avg_len = analysis["avg_length"]

    cat_map = {c["cat"]: c for c in analysis["categories"]}
    lb_map = {l["bucket"]: l for l in analysis["length_buckets"]}

    micro_pct = lb_map.get("micro (<20)", {}).get("pct", 0)
    short_pct = lb_map.get("short (20-50)", {}).get("pct", 0)
    debug_pct = cat_map.get("debugging", {}).get("pct", 0)
    test_pct = cat_map.get("testing", {}).get("pct", 0)
    ref_pct = cat_map.get("refactoring", {}).get("pct", 0)
    q_pct = cat_map.get("question", {}).get("pct", 0)
    build_pct = cat_map.get("building", {}).get("pct", 0)

    # 1. Prompt specificity
    if micro_pct + short_pct > 25:
        recs.append({
            "title": "Front-load context in your prompts",
            "severity": "high",
            "body": (
                f"{micro_pct + short_pct:.0f}% of your prompts are under 50 characters. "
                "Short prompts force Claude to guess, leading to extra back-and-forth. "
                "Include: what you want changed, which file, expected vs actual behavior, "
                "and constraints. A precise 100-char prompt saves 5 follow-ups."
            ),
            "metric": f"your avg: {avg_len} chars",
            "example": (
                'Instead of "fix the bug", try:\n'
                '"Fix the login form in src/auth/LoginForm.tsx - it shows a blank '
                'screen after submitting valid credentials. The handleSubmit callback '
                'should redirect to /dashboard but the router.push isn\'t firing."'
            ),
        })

    # 2. Debug ratio
    if debug_pct > 12:
        recs.append({
            "title": "Reduce debugging cycles",
            "severity": "high" if debug_pct > 20 else "medium",
            "body": (
                f"{debug_pct}% of your prompts are debugging. Reduce this by: "
                "1) pasting full error messages + stack traces upfront, "
                "2) asking Claude to add error handling proactively when building features, "
                "3) requesting defensive coding patterns like input validation."
            ),
            "metric": f"{debug_pct}% debugging | target: <10%",
            "example": (
                '"Implement the payment webhook handler. Add try/catch with '
                'descriptive error logging for each step, validate the webhook '
                'signature, and return appropriate HTTP status codes for each failure mode."'
            ),
        })

    # 3. Testing
    if test_pct < 5:
        recs.append({
            "title": "Ask for tests alongside features",
            "severity": "medium",
            "body": (
                f"Only {test_pct}% of prompts mention testing. "
                "Bundling test requests with feature work catches regressions early "
                "and forces Claude to think about edge cases during implementation."
            ),
            "metric": f"{test_pct}% testing | recommended: 10-15%",
            "example": (
                '"Implement the user search endpoint and write tests covering: '
                'empty query, special characters, pagination boundaries, and a '
                'user with no matching results."'
            ),
        })

    # 4. Refactoring
    if ref_pct < 3:
        recs.append({
            "title": "Schedule refactoring passes",
            "severity": "low",
            "body": (
                f"Only {ref_pct}% of prompts involve refactoring. "
                "After features ship, ask Claude to clean up. It excels at "
                "mechanical refactoring — extracting shared utils, simplifying "
                "complex functions, improving naming."
            ),
            "metric": f"{ref_pct}% refactoring | healthy: 5-10%",
            "example": (
                '"Review src/api/ for duplicated logic across endpoints. '
                'Extract shared patterns into middleware or utility functions. '
                'Don\'t change behavior, just clean up the structure."'
            ),
        })

    # 5. Questions
    if q_pct < 8:
        recs.append({
            "title": "Ask Claude to explain before building",
            "severity": "medium",
            "body": (
                f"Only {q_pct}% of prompts are questions. "
                "Before diving into implementation, use Claude as a thinking "
                "partner. A 30-second question can prevent a 30-minute wrong turn."
            ),
            "metric": f"{q_pct}% questions | consider: 10-15%",
            "example": (
                '"Before I implement caching, walk me through the tradeoffs '
                'between Redis and in-memory caching for our use case. '
                'We have ~1000 requests/min and the data changes every 5 minutes."'
            ),
        })

    # 6. Batching
    avg_msgs = summary["total_user_msgs"] / max(summary["total_sessions"], 1)
    if avg_msgs > 100:
        recs.append({
            "title": "Batch related changes into single prompts",
            "severity": "medium",
            "body": (
                f"You average {avg_msgs:.0f} messages per session. "
                "Try combining related changes: instead of 5 separate prompts "
                "for 5 files, list all changes in one prompt. Claude handles "
                "multi-file changes well and produces more coherent diffs."
            ),
            "metric": f"{avg_msgs:.0f} msgs/session avg",
            "example": (
                '"Rename userService to authService across the codebase: '
                '1) rename the file, 2) update all imports in src/, '
                '3) update tests, 4) update any references in config files."'
            ),
        })

    # 7. CLAUDE.md
    recs.append({
        "title": "Use CLAUDE.md for persistent context",
        "severity": "low",
        "body": (
            "Put project conventions, file structure, and recurring instructions "
            "in a CLAUDE.md file in your project root. Claude reads it at session "
            "start, eliminating repeated context-setting across sessions."
        ),
        "metric": f"{summary['total_sessions']} sessions could each save setup prompts",
        "example": (
            "# CLAUDE.md\n"
            "- This is a React Native app using Expo\n"
            "- Run tests with: npx jest --watchAll=false\n"
            "- Always use TypeScript strict mode\n"
            "- Prefer functional components with hooks\n"
            "- API base URL is in src/config/api.ts"
        ),
    })

    return recs


def get_ai_recommendations(analysis, summary, prompts_sample, work_days):
    """Generate recommendations using Claude API for deeper analysis."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY not set"

    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed (pip install anthropic)"

    client = anthropic.Anthropic(api_key=api_key)

    # Build a concise summary for the API
    cat_summary = ", ".join(
        f"{c['cat']}: {c['pct']}%" for c in analysis["categories"][:8]
    )
    len_summary = ", ".join(
        f"{l['bucket']}: {l['pct']}%" for l in analysis["length_buckets"]
    )

    # Sample prompts by category for analysis
    sample_by_cat = {}
    for p in prompts_sample:
        cat = p["category"]
        if cat not in sample_by_cat:
            sample_by_cat[cat] = []
        if len(sample_by_cat[cat]) < 3:
            sample_by_cat[cat].append(p["text"][:200])

    sample_text = ""
    for cat, samples in list(sample_by_cat.items())[:6]:
        sample_text += f"\n{cat}:\n"
        for s in samples:
            sample_text += f'  - "{s}"\n'

    # Work pattern summary
    if work_days:
        total_active = sum(d["active_hrs"] for d in work_days)
        avg_daily = total_active / len(work_days)
        work_summary = (
            f"Active days: {len(work_days)}, "
            f"avg active hours/day: {avg_daily:.1f}h, "
            f"total active hours: {total_active:.1f}h"
        )
    else:
        work_summary = "No work pattern data available"

    prompt = f"""Analyze this Claude Code user's usage patterns and provide specific, actionable recommendations to improve their productivity.

## Usage Stats
- Total prompts: {analysis['total_prompts']}
- Average prompt length: {analysis['avg_length']} chars
- Sessions: {summary['total_sessions']} across {summary['unique_projects']} projects
- Date range: {summary['date_range_start']} to {summary['date_range_end']}
- {work_summary}

## Prompt Categories
{cat_summary}

## Prompt Length Distribution
{len_summary}

## Sample Prompts by Category
{sample_text}

## Project Quality
{json.dumps(analysis['project_quality'][:5], indent=2)}

Provide exactly 5 recommendations as a JSON array. Each recommendation should have:
- "title": short actionable title (imperative mood)
- "severity": "high", "medium", or "low"
- "body": 2-3 sentence explanation referencing their specific numbers
- "metric": one-line stat with current vs target
- "example": a concrete example prompt they could use instead

Focus on the highest-impact changes. Reference their actual numbers. Be specific, not generic.
Return ONLY valid JSON, no markdown fences."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Try to parse JSON
        if text.startswith("["):
            recs = json.loads(text)
        else:
            # Try to extract JSON from response
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

    # Always generate heuristic recs as fallback
    heuristic_recs = get_heuristic_recommendations(analysis, summary, work_days)

    if not use_api:
        print("  Using heuristic analysis (--no-api)")
        return {"recommendations": heuristic_recs, "source": "heuristic"}

    print("  Generating AI-powered recommendations...")
    ai_recs, error = get_ai_recommendations(
        analysis, summary, data.get("prompts", [])[:50], work_days
    )

    if ai_recs:
        print("  AI recommendations generated successfully")
        return {"recommendations": ai_recs, "source": "ai"}
    else:
        print(f"  AI analysis unavailable ({error}), using heuristic analysis")
        return {"recommendations": heuristic_recs, "source": "heuristic"}

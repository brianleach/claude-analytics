"""AI-powered prompt analysis using Claude API."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path


def find_example_prompts(prompts: list[dict], category: str, max_count: int = 3, max_len: int = 150) -> list[str]:
    """Find real example prompts from a specific category."""
    matches = [p for p in prompts if p.get("category") == category and len(p.get("text", "")) > 15]
    # Prefer shorter prompts that illustrate the problem
    matches.sort(key=lambda p: p.get("full_length", 0))
    return [p["text"][:max_len] for p in matches[:max_count]]


def find_short_prompts(prompts: list[dict], max_chars: int = 50, max_count: int = 5) -> list[str]:
    """Find real examples of short prompts the user sent."""
    short = [p for p in prompts if p.get("full_length", 0) < max_chars and len(p.get("text", "").strip()) > 3]
    # Pick a diverse sample
    if len(short) > max_count:
        step = len(short) // max_count
        short = [short[i * step] for i in range(max_count)]
    return [p["text"][:80] for p in short]


_RULES_CACHE: list[dict] | None = None


def _load_rules() -> list[dict]:
    """Load heuristic rules from shared JSON (cached after first load)."""
    global _RULES_CACHE
    if _RULES_CACHE is not None:
        return _RULES_CACHE
    rules_path = Path(__file__).resolve().parent.parent.parent.parent / "shared" / "heuristic_rules.json"
    with open(rules_path) as f:
        _RULES_CACHE = json.load(f)
    return _RULES_CACHE


def _render_template(template: str, values: dict) -> str:
    """Render a template string with {{variable}} and {{variable:.0f}} placeholders."""
    def replacer(m):
        key = m.group(1)
        fmt = m.group(2) or ""
        val = values.get(key, "")
        if fmt:
            try:
                return f"{val:{fmt}}"
            except (ValueError, TypeError):
                return str(val)
        return str(val)
    return re.sub(r"\{\{(\w+)(?::([^}]+))?\}\}", replacer, template)


def _check_condition(cond: dict, values: dict) -> bool:
    """Check a simple condition {metric, operator, threshold} against values."""
    metric_val = values.get(cond["metric"], 0)
    op = cond["operator"]
    # threshold can be a number or a reference to another metric
    if "threshold_metric" in cond:
        threshold = values.get(cond["threshold_metric"], 0)
    else:
        threshold = cond["threshold"]
    if op == ">":
        return metric_val > threshold
    elif op == "<":
        return metric_val < threshold
    elif op == ">=":
        return metric_val >= threshold
    elif op == "<=":
        return metric_val <= threshold
    return False


def get_heuristic_recommendations(
    analysis: dict,
    summary: dict,
    work_days: list[dict] | None,
    prompts: list[dict] | None = None,
    models: list[dict] | None = None,
    subagents: dict | None = None,
    context_efficiency: dict | None = None,
    branches: list[dict] | None = None,
    skills: list[dict] | None = None,
    permission_modes: dict | None = None,
) -> list[dict]:
    """Generate recommendations using shared heuristic rules (no API needed)."""
    rules = _load_rules()
    recs = []
    total = analysis["total_prompts"]
    avg_len = analysis["avg_length"]
    prompts = prompts or []
    models = models or []
    subagents = subagents or {}
    context_efficiency = context_efficiency or {}
    branches = branches or []
    skills = skills or []
    permission_modes = permission_modes or {}

    cat_map = {c["cat"]: c for c in analysis["categories"]}
    lb_map = {l["bucket"]: l for l in analysis["length_buckets"]}

    micro_pct = lb_map.get("micro (<20)", {}).get("pct", 0)
    short_pct = lb_map.get("short (20-50)", {}).get("pct", 0)
    debug_pct = cat_map.get("debugging", {}).get("pct", 0)
    test_pct = cat_map.get("testing", {}).get("pct", 0)
    ref_pct = cat_map.get("refactoring", {}).get("pct", 0)
    q_pct = cat_map.get("question", {}).get("pct", 0)
    build_pct = cat_map.get("building", {}).get("pct", 0)
    confirm_pct = cat_map.get("confirmation", {}).get("pct", 0)

    # Computed metrics
    avg_msgs = summary["total_user_msgs"] / max(summary["total_sessions"], 1)
    total_sessions = summary["total_sessions"]

    opus_pct = 0
    if models:
        opus_model = next((m for m in models if m["display"] == "Opus"), None)
        total_cost = summary.get("estimated_cost", 0)
        if opus_model and total_cost > 0:
            opus_pct = round(opus_model["estimated_cost"] / total_cost * 100)

    sa_count = subagents.get("total_count", 0)
    sa_types = subagents.get("type_counts", {})
    explore_count = sa_types.get("Explore", 0)
    gp_count = sa_types.get("general-purpose", 0)
    compaction_count = subagents.get("compaction_count", 0)

    tool_pct = context_efficiency.get("tool_pct", 0)
    conversation_pct = context_efficiency.get("conversation_pct", 0)
    thinking = context_efficiency.get("thinking_blocks", 0)
    thinking_per_session = thinking / max(total_sessions, 1)

    skill_count = len(skills)

    default_pm = permission_modes.get("default", 0)
    total_pm = sum(permission_modes.values()) or 1
    default_pm_ratio = default_pm / total_pm
    default_pm_pct = default_pm_ratio * 100

    format_prompt_count = len([p for p in prompts if any(
        w in p.get("text", "").lower()
        for w in ["lint", "format", "prettier", "eslint", "formatting"]
    )])

    long_session_count = len([s for s in (work_days or []) if s.get("active_hrs", 0) > 4])

    # All template values
    values = {
        "total": total, "avg_len": avg_len,
        "micro_pct": micro_pct, "short_pct": short_pct,
        "micro_short_pct": micro_pct + short_pct,
        "debug_pct": debug_pct, "test_pct": test_pct,
        "ref_pct": ref_pct, "q_pct": q_pct,
        "build_pct": build_pct, "confirm_pct": confirm_pct,
        "avg_msgs": avg_msgs, "total_sessions": total_sessions,
        "opus_pct": opus_pct,
        "sa_count": sa_count, "explore_count": explore_count, "gp_count": gp_count,
        "compaction_count": compaction_count,
        "tool_pct": tool_pct, "conversation_pct": conversation_pct,
        "thinking": thinking, "thinking_per_session": thinking_per_session,
        "skill_count": skill_count,
        "default_pm_ratio": default_pm_ratio, "default_pm_pct": default_pm_pct,
        "format_prompt_count": format_prompt_count,
        "long_session_count": long_session_count,
    }

    triggered_ids = set()

    for rule in rules:
        # Evaluate condition
        cond = rule["condition"]
        ctype = cond["type"]

        if ctype == "simple":
            if not _check_condition(cond, values):
                continue
        elif ctype == "sum_gt":
            total_val = sum(values.get(m, 0) for m in cond["metrics"])
            if total_val <= cond["threshold"]:
                continue
        elif ctype == "or":
            if not any(_check_condition(c, values) for c in cond["conditions"]):
                continue
        elif ctype == "compound_and":
            if not all(_check_condition(c, values) for c in cond["conditions"]):
                continue
            if cond.get("excludes") and cond["excludes"] in triggered_ids:
                continue
        elif ctype == "computed":
            if not _check_condition(
                {"metric": cond["computed_metric"], "operator": cond["operator"],
                 "threshold": cond["threshold"]},
                values,
            ):
                continue
        else:
            continue

        triggered_ids.add(rule["id"])

        # Determine severity
        severity = rule["severity"]
        if "severity_override" in rule:
            so = rule["severity_override"]
            if _check_condition(so["condition"], values):
                severity = so["severity"]

        # Determine body text
        if "body_variants" in rule:
            variant = "default"
            bvc = rule.get("body_variant_condition")
            if bvc and _check_condition(bvc, values):
                variant = bvc["variant"]
            body = _render_template(rule["body_variants"][variant], values)
        else:
            body = _render_template(rule["body_template"], values)

        metric = _render_template(rule["metric_template"], values)

        # Build example with real prompt data when available
        example = ""
        example_type = rule.get("example_type")
        if example_type == "short_prompts":
            short_examples = find_short_prompts(prompts)
            if short_examples:
                example = rule["example_preamble"] + "\n"
                for ex in short_examples[:3]:
                    example += f'  > "{ex}"\n'
                example += "\n" + rule["example_suggestion"]
        elif example_type == "category_prompts":
            cat = rule["example_category"]
            max_count = rule.get("example_max_count", 3)
            cat_examples = find_example_prompts(prompts, cat, max_count)
            if cat_examples:
                example = rule["example_preamble"] + "\n"
                for ex in cat_examples[:max_count]:
                    example += f'  > "{ex}"\n'
                example += "\n" + rule["example_suggestion"]

        if not example:
            example = rule["fallback_example"]

        recs.append({
            "title": rule["title"],
            "severity": severity,
            "body": body,
            "metric": metric,
            "example": example,
        })

    return recs


def get_ai_recommendations(analysis, summary, prompts_sample, work_days,
                            models=None, subagents=None, context_efficiency=None,
                            branches=None, skills=None, permission_modes=None):
    """Generate recommendations using Claude API for deeper, personalized analysis."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None, "ANTHROPIC_API_KEY not set"

    try:
        import anthropic
    except ImportError:
        return None, "anthropic package not installed (pip install anthropic)"

    client = anthropic.Anthropic(api_key=api_key)

    # === Build rich context ===
    cat_summary = ", ".join(
        f"{c['cat']}: {c['pct']}%" for c in analysis["categories"][:8]
    )
    len_summary = ", ".join(
        f"{l['bucket']}: {l['pct']}%" for l in analysis["length_buckets"]
    )

    # Sample prompts by category (real examples)
    sample_by_cat = {}
    for p in prompts_sample:
        cat = p["category"]
        if cat not in sample_by_cat:
            sample_by_cat[cat] = []
        if len(sample_by_cat[cat]) < 5:
            sample_by_cat[cat].append({
                "text": p["text"][:300],
                "length": p.get("full_length", len(p["text"])),
                "project": p.get("project", ""),
            })

    sample_text = ""
    for cat, samples in sorted(sample_by_cat.items(), key=lambda x: -len(x[1])):
        sample_text += f"\n### {cat} ({len(samples)} samples)\n"
        for s in samples:
            sample_text += f'  [{s["project"]}] ({s["length"]}ch) "{s["text"]}"\n'

    # Work pattern
    work_summary = "No work pattern data"
    if work_days:
        total_active = sum(d["active_hrs"] for d in work_days)
        avg_daily = total_active / len(work_days)
        avg_prompts = sum(d["prompts"] for d in work_days) / len(work_days)
        work_summary = (
            f"Active days: {len(work_days)}, avg active hours/day: {avg_daily:.1f}h, "
            f"avg prompts/day: {avg_prompts:.0f}, total active hours: {total_active:.1f}h"
        )

    # Model usage
    model_text = "No model data"
    if models:
        model_text = "\n".join(
            f"  {m['display']}: {m['msgs']} msgs, ${m['estimated_cost']:.2f} estimated cost"
            for m in models if m["msgs"] > 0
        )

    # Subagent usage
    sa_text = "No subagent data"
    if subagents and subagents.get("total_count", 0) > 0:
        sa = subagents
        sa_text = (
            f"Total: {sa['total_count']}, Compactions: {sa['compaction_count']}\n"
            f"  Types: {json.dumps(sa.get('type_counts', {}))}\n"
            f"  Subagent cost: ${sa.get('estimated_cost', 0):.2f}"
        )

    # Context efficiency
    ce_text = "No context data"
    if context_efficiency:
        ce = context_efficiency
        ce_text = (
            f"Tool output: {ce.get('tool_pct', 0)}%, Conversation: {ce.get('conversation_pct', 0)}%, "
            f"Thinking blocks: {ce.get('thinking_blocks', 0)}, "
            f"Subagent output share: {ce.get('subagent_pct', 0)}%"
        )

    # Branch summary
    branch_text = "No branch data"
    if branches:
        branch_text = "\n".join(
            f"  {b['branch']}: {b['msgs']} msgs, {b['sessions']} sessions"
            for b in branches[:10]
        )

    # Permission modes
    permission_modes = permission_modes or {}
    pm_text = "No permission data"
    if permission_modes:
        total_pm = sum(permission_modes.values())
        pm_text = ", ".join(
            f"{k}: {v} ({round(v/total_pm*100)}%)"
            for k, v in sorted(permission_modes.items(), key=lambda x: -x[1])
        )

    # Load shared prompt template
    prompt_path = Path(__file__).resolve().parent.parent.parent.parent / "shared" / "ai_prompt.txt"
    with open(prompt_path) as f:
        prompt_template = f.read()

    overview = (
        f"- {analysis['total_prompts']} prompts across {summary['total_sessions']} sessions, {summary['unique_projects']} projects\n"
        f"- Date range: {summary['date_range_start']} to {summary['date_range_end']}\n"
        f"- Average prompt length: {analysis['avg_length']} chars\n"
        f"- Estimated API cost: ${summary.get('estimated_cost', 0):.2f}\n"
        f"- {work_summary}"
    )

    prompt = (prompt_template
        .replace("{{overview}}", overview)
        .replace("{{categories}}", cat_summary)
        .replace("{{length_distribution}}", len_summary)
        .replace("{{model_usage}}", model_text)
        .replace("{{subagent_usage}}", sa_text)
        .replace("{{context_efficiency}}", ce_text)
        .replace("{{branch_activity}}", branch_text)
        .replace("{{permission_modes}}", pm_text)
        .replace("{{project_quality}}", json.dumps(analysis['project_quality'][:8], indent=2))
        .replace("{{sample_prompts}}", sample_text)
    )

    # Spinner runs in a background thread during the API call
    stop_spinner = threading.Event()

    def spinner():
        phases = [
            "Analyzing prompt patterns",
            "Evaluating model usage",
            "Reviewing session efficiency",
            "Checking workflow patterns",
            "Generating personalized tips",
        ]
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        t0 = time.time()
        while not stop_spinner.is_set():
            elapsed = int(time.time() - t0)
            phase = phases[min(elapsed // 10, len(phases) - 1)]
            sys.stdout.write(f"\r  {chars[i % len(chars)]} {phase}... ({elapsed}s)")
            sys.stdout.flush()
            i += 1
            stop_spinner.wait(0.1)
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()

    spin_thread = threading.Thread(target=spinner, daemon=True)
    spin_thread.start()

    try:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        stop_spinner.set()
        spin_thread.join()
        text = response.content[0].text.strip()
        if text.startswith("["):
            recs = json.loads(text)
        else:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                recs = json.loads(text[start:end])
            else:
                return None, "Could not parse API response as JSON"
        return recs, None
    except Exception as e:
        stop_spinner.set()
        spin_thread.join()
        return None, str(e)


def generate_recommendations(data: dict, use_api: bool = True) -> dict:
    """Generate recommendations, trying API first then falling back to heuristics.

    Returns:
        dict with 'recommendations' list and 'source' ('ai' or 'heuristic')
    """
    analysis = data["analysis"]
    summary = data["dashboard"]["summary"]
    work_days = data.get("work_days", [])
    prompts = data.get("prompts", [])
    models = data.get("models", [])
    subagents = data.get("subagents", {})
    context_efficiency = data.get("context_efficiency", {})
    branches = data.get("branches", [])
    skills = data.get("skills", [])
    permission_modes = data.get("permission_modes", {})

    # Always generate heuristic recs
    heuristic_recs = get_heuristic_recommendations(
        analysis, summary, work_days, prompts,
        models, subagents, context_efficiency, branches, skills,
        permission_modes
    )

    if not use_api:
        print("  Using heuristic analysis (--no-api)")
        for r in heuristic_recs:
            r["rec_source"] = "heuristic"
        return {"recommendations": heuristic_recs, "source": "heuristic"}

    ai_recs, error = get_ai_recommendations(
        analysis, summary, prompts[:80], work_days,
        models, subagents, context_efficiency, branches, skills,
        permission_modes
    )

    if ai_recs:
        # Tag sources
        for r in ai_recs:
            r["rec_source"] = "ai"
        for r in heuristic_recs:
            r["rec_source"] = "heuristic"

        merged = ai_recs + heuristic_recs
        print(f"  {len(ai_recs)} AI + {len(heuristic_recs)} heuristic = {len(merged)} recommendations")
        return {"recommendations": merged, "source": "ai"}
    else:
        print(f"  AI analysis unavailable ({error}), using heuristic analysis")
        return {"recommendations": heuristic_recs, "source": "heuristic"}

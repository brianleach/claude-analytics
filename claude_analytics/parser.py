"""Parse Claude Code session data from ~/.claude/ directory."""

import json
import os
import re
import glob
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path


def detect_timezone_offset():
    """Detect the local timezone offset from UTC in hours."""
    now = datetime.now()
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    offset = now - utc_now
    return round(offset.total_seconds() / 3600)


def find_claude_dir():
    """Find the ~/.claude directory."""
    claude_dir = Path.home() / ".claude"
    if not claude_dir.exists():
        raise FileNotFoundError(
            f"Claude directory not found at {claude_dir}\n"
            "Make sure you have Claude Code installed and have used it at least once."
        )
    return claude_dir


def find_session_files(claude_dir):
    """Find all main session JSONL files (excluding subagents)."""
    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        raise FileNotFoundError(f"No projects directory found at {projects_dir}")

    all_jsonl = list(projects_dir.glob("*/*.jsonl"))
    # Filter out subagent files
    main_sessions = [f for f in all_jsonl if "subagent" not in str(f)]
    return main_sessions


def clean_project_name(dirname):
    """Convert directory name to readable project name."""
    name = dirname
    # Remove common prefixes
    home = str(Path.home()).replace("/", "-").replace("\\", "-")
    if home.startswith("-"):
        home = home[1:]
    name = name.replace(home + "-", "").replace(home, "home")
    # Clean up remaining dashes
    if name.startswith("-"):
        name = name[1:]
    return name or "unknown"


def categorize_prompt(text):
    """Categorize a user prompt by intent."""
    t = text.lower().strip()
    if len(t) < 5:
        return "micro"

    if re.match(
        r"^(y(es)?|yeah|yep|ok(ay)?|sure|go|do it|proceed|looks good|lgtm|"
        r"correct|right|confirm|approved|continue|k|yea|np|go ahead|ship it|"
        r"perfect|great|nice|good|cool|thanks|ty|thx)\s*$",
        t,
    ):
        return "confirmation"

    if any(
        w in t
        for w in [
            "error", "bug", "fix", "broken", "crash", "fail", "issue",
            "wrong", "not working", "doesn't work", "won't", "undefined",
            "null", "exception", "traceback",
        ]
    ):
        return "debugging"

    if any(
        w in t
        for w in [
            "add", "create", "build", "implement", "make", "new feature",
            "set up", "setup", "write", "generate",
        ]
    ):
        return "building"

    if any(
        w in t
        for w in [
            "refactor", "clean up", "rename", "move", "restructure",
            "reorganize", "simplify", "extract",
        ]
    ):
        return "refactoring"

    if t.startswith((
        "how", "what", "why", "where", "when", "can you", "is there",
        "do we", "does", "which", "should",
    )):
        return "question"

    if any(
        w in t
        for w in [
            "review", "check", "look at", "examine", "inspect", "analyze",
            "show me", "read", "list", "find",
        ]
    ):
        return "review"

    if any(
        w in t
        for w in ["update", "change", "modify", "edit", "replace", "remove",
                   "delete", "tweak", "adjust"]
    ):
        return "editing"

    if any(w in t for w in ["test", "spec", "coverage", "assert", "expect"]):
        return "testing"

    if any(
        w in t
        for w in [
            "commit", "push", "deploy", "merge", "branch", "pr ",
            "pull request", "git ",
        ]
    ):
        return "git_ops"

    if len(t) < 30:
        return "brief"

    return "detailed"


def length_bucket(length):
    """Classify prompt length into a bucket."""
    if length < 20:
        return "micro (<20)"
    if length < 50:
        return "short (20-50)"
    if length < 150:
        return "medium (50-150)"
    if length < 500:
        return "detailed (150-500)"
    return "comprehensive (500+)"


def parse_all_sessions(claude_dir, tz_offset=None):
    """Parse all session data and return structured analytics.

    Args:
        claude_dir: Path to ~/.claude directory
        tz_offset: Timezone offset from UTC in hours (auto-detected if None)

    Returns:
        dict with all parsed and analyzed data
    """
    if tz_offset is None:
        tz_offset = detect_timezone_offset()

    session_files = find_session_files(claude_dir)

    if not session_files:
        raise ValueError(
            "No session files found. Use Claude Code for a while first!"
        )

    # === Pass 1: Extract all messages ===
    all_messages = []
    sessions_meta = []
    prompts = []
    drilldown = defaultdict(lambda: defaultdict(list))

    for filepath in session_files:
        project_dir = filepath.parent.name
        proj_name = clean_project_name(project_dir)
        session_id = filepath.stem

        timestamps = []
        user_msgs = 0
        assistant_msgs = 0
        tool_uses = 0
        model = None
        entrypoint = None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_type = d.get("type")
                    ts = d.get("timestamp")

                    if msg_type == "user" and ts:
                        user_msgs += 1
                        if not entrypoint:
                            entrypoint = d.get("entrypoint")

                        dt = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")
                        ) + timedelta(hours=tz_offset)

                        msg_data = {
                            "timestamp": ts,
                            "date": dt.strftime("%Y-%m-%d"),
                            "time": dt.strftime("%H:%M"),
                            "hour": dt.hour,
                            "weekday": dt.weekday(),
                            "weekday_name": dt.strftime("%A"),
                            "month": dt.strftime("%Y-%m"),
                            "type": "user",
                            "project": proj_name,
                            "session_id": session_id[:8],
                        }
                        all_messages.append(msg_data)
                        timestamps.append(ts)

                        # Extract prompt text
                        msg = d.get("message", {})
                        text = ""
                        is_tool_result = False

                        if isinstance(msg, dict):
                            content = msg.get("content", "")
                            if isinstance(content, str):
                                text = content.strip()
                            elif isinstance(content, list):
                                has_text = False
                                for c in content:
                                    if isinstance(c, dict):
                                        if (
                                            c.get("type") == "text"
                                            and c.get("text", "").strip()
                                        ):
                                            text += c["text"] + " "
                                            has_text = True
                                        elif c.get("type") == "tool_result":
                                            is_tool_result = True
                                text = text.strip()
                                if not has_text and is_tool_result:
                                    text = ""

                        if text:
                            prompt = {
                                "text": text[:500],
                                "full_length": len(text),
                                "project": proj_name,
                                "session_id": session_id[:8],
                                "date": dt.strftime("%Y-%m-%d"),
                                "time": dt.strftime("%H:%M"),
                                "hour": dt.hour,
                                "weekday": dt.weekday(),
                                "category": categorize_prompt(text),
                                "length_bucket": length_bucket(len(text)),
                            }
                            prompts.append(prompt)
                            drilldown[prompt["date"]][proj_name].append({
                                "time": prompt["time"],
                                "text": prompt["text"][:200],
                                "category": prompt["category"],
                                "length": prompt["full_length"],
                            })

                    elif msg_type == "assistant" and ts:
                        assistant_msgs += 1
                        timestamps.append(ts)

                        dt = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")
                        ) + timedelta(hours=tz_offset)

                        msg = d.get("message", {})
                        msg_model = None
                        msg_tools = []
                        input_tokens = 0
                        output_tokens = 0

                        if isinstance(msg, dict):
                            msg_model = msg.get("model", "")
                            if msg_model:
                                model = msg_model
                            content = msg.get("content", [])
                            if isinstance(content, list):
                                msg_tools = [
                                    c.get("name", "")
                                    for c in content
                                    if isinstance(c, dict)
                                    and c.get("type") == "tool_use"
                                ]
                                tool_uses += len(msg_tools)
                            usage = msg.get("usage", {})
                            if usage:
                                input_tokens = usage.get("input_tokens", 0)
                                output_tokens = usage.get("output_tokens", 0)

                        all_messages.append({
                            "timestamp": ts,
                            "date": dt.strftime("%Y-%m-%d"),
                            "hour": dt.hour,
                            "weekday": dt.weekday(),
                            "type": "assistant",
                            "project": proj_name,
                            "session_id": session_id[:8],
                            "tool_uses": msg_tools,
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "model": msg_model or "",
                        })

        except Exception:
            continue

        if timestamps:
            sessions_meta.append({
                "project": proj_name,
                "session_id": session_id[:8],
                "first_ts": min(timestamps),
                "last_ts": max(timestamps),
                "user_msgs": user_msgs,
                "assistant_msgs": assistant_msgs,
                "tool_uses": tool_uses,
                "model": model,
                "entrypoint": entrypoint,
                "msg_count": user_msgs + assistant_msgs,
            })

    # === Pass 2: Aggregate ===
    user_messages = [m for m in all_messages if m["type"] == "user"]
    asst_messages = [m for m in all_messages if m["type"] == "assistant"]

    # Daily data
    daily_user = defaultdict(int)
    daily_asst = defaultdict(int)
    daily_tools = defaultdict(int)
    daily_tokens = defaultdict(int)
    for m in user_messages:
        daily_user[m["date"]] += 1
    for m in asst_messages:
        daily_asst[m["date"]] += 1
        daily_tools[m["date"]] += len(m.get("tool_uses", []))
        daily_tokens[m["date"]] += m.get("output_tokens", 0)

    all_dates = sorted(set(list(daily_user.keys()) + list(daily_asst.keys())))
    daily_data = [
        {
            "date": d,
            "user_msgs": daily_user[d],
            "assistant_msgs": daily_asst[d],
            "tool_calls": daily_tools[d],
            "output_tokens": daily_tokens[d],
            "total_msgs": daily_user[d] + daily_asst[d],
        }
        for d in all_dates
    ]

    # Heatmap
    heatmap_data = []
    heatmap_counts = defaultdict(int)
    for m in user_messages:
        heatmap_counts[f"{m['weekday']}_{m['hour']}"] += 1
    for wd in range(7):
        for hr in range(24):
            heatmap_data.append({
                "weekday": wd,
                "hour": hr,
                "count": heatmap_counts.get(f"{wd}_{hr}", 0),
            })

    # Project stats
    project_stats = defaultdict(
        lambda: {
            "user_msgs": 0, "assistant_msgs": 0, "tool_calls": 0,
            "sessions": set(), "output_tokens": 0,
        }
    )
    for m in all_messages:
        p = m["project"]
        project_stats[p]["sessions"].add(m.get("session_id", ""))
        if m["type"] == "user":
            project_stats[p]["user_msgs"] += 1
        else:
            project_stats[p]["assistant_msgs"] += 1
            project_stats[p]["tool_calls"] += len(m.get("tool_uses", []))
            project_stats[p]["output_tokens"] += m.get("output_tokens", 0)

    project_data = sorted(
        [
            {
                "project": p,
                "user_msgs": s["user_msgs"],
                "assistant_msgs": s["assistant_msgs"],
                "tool_calls": s["tool_calls"],
                "sessions": len(s["sessions"]),
                "output_tokens": s["output_tokens"],
                "total_msgs": s["user_msgs"] + s["assistant_msgs"],
            }
            for p, s in project_stats.items()
        ],
        key=lambda x: -x["total_msgs"],
    )

    # Tool stats
    tool_counts = defaultdict(int)
    for m in asst_messages:
        for t in m.get("tool_uses", []):
            tool_counts[t] += 1
    tool_data = [
        {"tool": t, "count": c}
        for t, c in sorted(tool_counts.items(), key=lambda x: -x[1])[:20]
    ]

    # Hourly
    hourly_counts = defaultdict(int)
    for m in user_messages:
        hourly_counts[m["hour"]] += 1
    hourly_data = [{"hour": h, "count": hourly_counts.get(h, 0)} for h in range(24)]

    # Session durations
    session_durations = []
    for s in sessions_meta:
        try:
            t1 = datetime.fromisoformat(s["first_ts"].replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(s["last_ts"].replace("Z", "+00:00"))
            dur = (t2 - t1).total_seconds() / 60
            t1_local = t1 + timedelta(hours=tz_offset)
            session_durations.append({
                "session_id": s["session_id"],
                "project": s["project"],
                "duration_min": round(dur, 1),
                "user_msgs": s["user_msgs"],
                "assistant_msgs": s["assistant_msgs"],
                "tool_uses": s["tool_uses"],
                "date": t1_local.strftime("%Y-%m-%d"),
                "start_hour": t1_local.hour,
                "msgs_per_min": round(
                    s["msg_count"] / max(dur, 1), 2
                ),
            })
        except Exception:
            continue

    # Weekly
    weekly_agg = defaultdict(lambda: {"user_msgs": 0, "sessions": set()})
    for m in user_messages:
        dt = datetime.fromisoformat(m["timestamp"].replace("Z", "+00:00"))
        week = dt.strftime("%Y-W%V")
        weekly_agg[week]["user_msgs"] += 1
        weekly_agg[week]["sessions"].add(m.get("session_id", ""))
    weekly_data = sorted(
        [
            {"week": w, "user_msgs": d["user_msgs"], "sessions": len(d["sessions"])}
            for w, d in weekly_agg.items()
        ],
        key=lambda x: x["week"],
    )

    # Efficiency by start hour
    hour_eff = defaultdict(
        lambda: {"total_msgs": 0, "sessions": 0, "duration_total": 0}
    )
    for sd in session_durations:
        h = sd["start_hour"]
        hour_eff[h]["total_msgs"] += sd["user_msgs"] + sd["assistant_msgs"]
        hour_eff[h]["sessions"] += 1
        hour_eff[h]["duration_total"] += sd["duration_min"]
    efficiency_data = [
        {
            "hour": h,
            "avg_msgs_per_session": round(e["total_msgs"] / e["sessions"], 1),
            "avg_duration": round(e["duration_total"] / e["sessions"], 1),
            "sessions": e["sessions"],
        }
        for h in range(24)
        if (e := hour_eff[h])["sessions"] > 0
    ]

    # Working hours estimate
    daily_spans = defaultdict(list)
    for m in user_messages:
        dt = datetime.fromisoformat(
            m["timestamp"].replace("Z", "+00:00")
        ) + timedelta(hours=tz_offset)
        daily_spans[dt.strftime("%Y-%m-%d")].append(dt)

    work_days = []
    for day, times in sorted(daily_spans.items()):
        times.sort()
        span_hrs = (times[-1] - times[0]).total_seconds() / 3600
        # Active hours: count time between messages with < 30 min gap
        active_secs = 120  # first message
        for i in range(1, len(times)):
            gap = (times[i] - times[i - 1]).total_seconds()
            active_secs += min(gap, 1800)
        active_hrs = active_secs / 3600
        work_days.append({
            "date": day,
            "first": times[0].strftime("%H:%M"),
            "last": times[-1].strftime("%H:%M"),
            "span_hrs": round(span_hrs, 1),
            "active_hrs": round(active_hrs, 1),
            "prompts": len(times),
        })

    # Prompt analysis
    cat_counts = defaultdict(int)
    lb_counts = defaultdict(int)
    proj_quality = defaultdict(
        lambda: {"count": 0, "total_len": 0, "confirms": 0, "detailed": 0, "cats": defaultdict(int)}
    )
    for p in prompts:
        cat_counts[p["category"]] += 1
        lb_counts[p["length_bucket"]] += 1
        pq = proj_quality[p["project"]]
        pq["count"] += 1
        pq["total_len"] += p["full_length"]
        if p["category"] in ("confirmation", "micro"):
            pq["confirms"] += 1
        if p["full_length"] > 100:
            pq["detailed"] += 1
        pq["cats"][p["category"]] += 1

    analysis = {
        "total_prompts": len(prompts),
        "avg_length": round(
            sum(p["full_length"] for p in prompts) / max(len(prompts), 1)
        ),
        "categories": [
            {"cat": c, "count": n, "pct": round(n / max(len(prompts), 1) * 100, 1)}
            for c, n in sorted(cat_counts.items(), key=lambda x: -x[1])
        ],
        "length_buckets": [
            {
                "bucket": b,
                "count": lb_counts.get(b, 0),
                "pct": round(lb_counts.get(b, 0) / max(len(prompts), 1) * 100, 1),
            }
            for b in [
                "micro (<20)", "short (20-50)", "medium (50-150)",
                "detailed (150-500)", "comprehensive (500+)",
            ]
        ],
        "project_quality": sorted(
            [
                {
                    "project": p,
                    "count": d["count"],
                    "avg_len": round(d["total_len"] / d["count"]),
                    "confirm_pct": round(d["confirms"] / d["count"] * 100, 1),
                    "detailed_pct": round(d["detailed"] / d["count"] * 100, 1),
                    "top_cat": max(d["cats"].items(), key=lambda x: x[1])[0],
                }
                for p, d in proj_quality.items()
                if d["count"] >= 5
            ],
            key=lambda x: -x["count"],
        ),
    }

    # Model stats
    model_counts = defaultdict(int)
    for m in asst_messages:
        model_counts[m.get("model", "unknown")] += 1

    total_output = sum(m.get("output_tokens", 0) for m in asst_messages)
    total_input = sum(m.get("input_tokens", 0) for m in asst_messages)

    summary = {
        "total_sessions": len(sessions_meta),
        "total_user_msgs": len(user_messages),
        "total_assistant_msgs": len(asst_messages),
        "total_tool_calls": sum(
            len(m.get("tool_uses", [])) for m in asst_messages
        ),
        "total_output_tokens": total_output,
        "total_input_tokens": total_input,
        "date_range_start": all_dates[0] if all_dates else "",
        "date_range_end": all_dates[-1] if all_dates else "",
        "unique_projects": len(project_stats),
        "unique_tools": len(tool_counts),
        "avg_session_duration": round(
            sum(s["duration_min"] for s in session_durations)
            / max(len(session_durations), 1),
            1,
        ),
        "tz_offset": tz_offset,
        "tz_label": f"UTC{tz_offset:+d}",
    }

    return {
        "dashboard": {
            "summary": summary,
            "daily": daily_data,
            "heatmap": heatmap_data,
            "projects": project_data,
            "tools": tool_data,
            "hourly": hourly_data,
            "sessions": session_durations,
            "weekly": weekly_data,
            "efficiency": efficiency_data,
        },
        "drilldown": dict(drilldown),
        "analysis": analysis,
        "prompts": prompts,
        "work_days": work_days,
    }

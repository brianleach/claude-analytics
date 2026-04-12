"""Parse Claude Code session data from ~/.claude/ directory."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path


# === COST ESTIMATES (per million tokens, USD) ===
MODEL_COSTS = {
    "claude-opus-4": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4": {"input": 0.80, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
}


def match_model_cost(model_str: str) -> dict[str, float]:
    """Match a model string to its cost tier."""
    m = (model_str or "").lower()
    if "opus" in m:
        return MODEL_COSTS["claude-opus-4"]
    if "sonnet" in m:
        return MODEL_COSTS["claude-sonnet-4"]
    if "haiku" in m:
        return MODEL_COSTS["claude-haiku-4"]
    # Default to sonnet pricing for unknown
    return MODEL_COSTS["claude-sonnet-4"]


def detect_timezone_offset() -> int:
    """Detect the local timezone offset from UTC in hours.

    Note: This may be slightly off during DST transitions.
    """
    now = datetime.now()
    utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
    offset = now - utc_now
    return round(offset.total_seconds() / 3600)


def find_claude_dir() -> Path:
    """Find the ~/.claude directory."""
    claude_dir = Path.home() / ".claude"
    if not claude_dir.exists():
        raise FileNotFoundError(
            f"Claude directory not found at {claude_dir}\n"
            "Make sure you have Claude Code installed and have used it at least once."
        )
    return claude_dir


def find_session_files(claude_dir: Path) -> list[Path]:
    """Find all main session JSONL files (excluding subagents)."""
    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        raise FileNotFoundError(f"No projects directory found at {projects_dir}")

    all_jsonl = list(projects_dir.glob("*/*.jsonl"))
    # Filter out subagent files
    main_sessions = [f for f in all_jsonl if "subagent" not in str(f)]
    return main_sessions


def find_subagent_files(claude_dir):
    """Find all subagent JSONL and meta files."""
    projects_dir = claude_dir / "projects"
    if not projects_dir.exists():
        return [], []
    jsonl_files = list(projects_dir.glob("*/*/subagents/*.jsonl"))
    meta_files = list(projects_dir.glob("*/*/subagents/*.meta.json"))
    return jsonl_files, meta_files


def clean_project_name(dirname: str) -> str:
    """Convert directory name to readable project name."""
    name = dirname
    home = str(Path.home()).replace("/", "-").replace("\\", "-")
    if home.startswith("-"):
        home = home[1:]
    name = name.replace(home + "-", "").replace(home, "home")
    if name.startswith("-"):
        name = name[1:]
    return name or "unknown"


def normalize_model_name(model_str: str) -> str:
    """Normalize model string to a clean display name."""
    if not model_str:
        return "unknown"
    m = model_str.lower()
    if "opus" in m:
        return "Opus"
    if "sonnet" in m:
        return "Sonnet"
    if "haiku" in m:
        return "Haiku"
    return model_str


def _has_word(words: list[str], text: str) -> bool:
    """Check if any word from the list appears as a whole word in text."""
    return any(re.search(r'\b' + re.escape(w) + r'\b', text) for w in words)


def categorize_prompt(text: str) -> str:
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

    if _has_word(
        [
            "error", "bug", "fix", "broken", "crash", "fail", "issue",
            "wrong", "not working", "doesn't work", "won't", "undefined",
            "null", "exception", "traceback",
        ],
        t,
    ):
        return "debugging"

    if _has_word(
        [
            "add", "create", "build", "implement", "make", "new feature",
            "set up", "setup", "write", "generate",
        ],
        t,
    ):
        return "building"

    if _has_word(
        [
            "refactor", "clean up", "rename", "move", "restructure",
            "reorganize", "simplify", "extract",
        ],
        t,
    ):
        return "refactoring"

    if t.startswith((
        "how", "what", "why", "where", "when", "can you", "is there",
        "do we", "does", "which", "should",
    )):
        return "question"

    if _has_word(
        [
            "review", "check", "look at", "examine", "inspect", "analyze",
            "show me", "read", "list", "find",
        ],
        t,
    ):
        return "review"

    if _has_word(
        ["update", "change", "modify", "edit", "replace", "remove",
         "delete", "tweak", "adjust"],
        t,
    ):
        return "editing"

    if _has_word(["test", "spec", "coverage", "assert", "expect"], t):
        return "testing"

    if _has_word(
        [
            "commit", "push", "deploy", "merge", "branch", "pr ",
            "pull request", "git ",
        ],
        t,
    ):
        return "git_ops"

    if len(t) < 30:
        return "brief"

    return "detailed"


def length_bucket(length: int) -> str:
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


def parse_config(claude_dir):
    """Parse .claude.json for feature flags, plugins, and settings."""
    config_path = claude_dir / ".claude.json"
    config = {
        "has_config": False,
        "plugins": [],
        "feature_flags": [],
        "version_info": {},
    }

    if not config_path.exists():
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        config["has_config"] = True

        # Extract plugins from feature flags
        features = data.get("cachedGrowthBookFeatures", {})
        amber_lattice = features.get("tengu_amber_lattice", {})
        if isinstance(amber_lattice, dict):
            plugins = amber_lattice.get("value", [])
            if isinstance(plugins, list):
                config["plugins"] = [p for p in plugins if isinstance(p, str)]

        # Extract interesting feature flags
        flag_names = []
        for key, val in features.items():
            if isinstance(val, dict):
                flag_names.append({
                    "name": key.replace("tengu_", ""),
                    "enabled": bool(val.get("value")),
                })
            elif isinstance(val, bool):
                flag_names.append({"name": key.replace("tengu_", ""), "enabled": val})
        config["feature_flags"] = flag_names

        # Migration / account info
        config["version_info"] = {
            "migration_version": data.get("migrationVersion", ""),
            "first_start": data.get("firstStartTime", ""),
        }

    except Exception:
        pass

    return config


def parse_subagents(claude_dir, tz_offset):
    """Parse all subagent data."""
    jsonl_files, meta_files = find_subagent_files(claude_dir)

    # Build meta lookup
    meta_lookup = {}
    for mf in meta_files:
        try:
            with open(mf, "r", encoding="utf-8") as f:
                meta = json.load(f)
            agent_id = mf.stem.replace("agent-", "").replace(".meta", "")
            meta_lookup[agent_id] = {
                "type": meta.get("agentType", "unknown"),
                "description": meta.get("description", ""),
            }
        except Exception:
            continue

    # Parse subagent JSONL files
    subagents = []
    type_counts = defaultdict(int)
    model_tokens = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0})

    for filepath in jsonl_files:
        agent_id = filepath.stem.replace("agent-", "")
        is_compaction = "compact" in agent_id.lower()
        meta = meta_lookup.get(agent_id, {"type": "unknown", "description": ""})
        agent_type = meta["type"]
        type_counts[agent_type] += 1

        msg_count = 0
        tool_calls = 0
        input_tokens = 0
        output_tokens = 0
        cache_read = 0
        models_used = set()
        first_ts = None
        last_ts = None

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

                    ts = d.get("timestamp")
                    if ts:
                        if not first_ts or ts < first_ts:
                            first_ts = ts
                        if not last_ts or ts > last_ts:
                            last_ts = ts

                    msg = d.get("message", {})
                    if isinstance(msg, dict):
                        m = msg.get("model", "")
                        if m:
                            models_used.add(m)
                        usage = msg.get("usage", {})
                        if usage:
                            input_tokens += usage.get("input_tokens", 0)
                            output_tokens += usage.get("output_tokens", 0)
                            cache_read += usage.get("cache_read_input_tokens", 0)
                        content = msg.get("content", [])
                        if isinstance(content, list):
                            for c in content:
                                if isinstance(c, dict) and c.get("type") == "tool_use":
                                    tool_calls += 1

                    msg_count += 1

        except Exception:
            continue

        # Get parent project
        parent_session_dir = filepath.parent.parent.parent.name
        proj_name = clean_project_name(parent_session_dir)

        duration = 0
        if first_ts and last_ts:
            try:
                t1 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                duration = (t2 - t1).total_seconds() / 60
            except Exception:
                pass

        subagents.append({
            "agent_id": agent_id[:12],
            "type": agent_type,
            "description": meta["description"][:80],
            "is_compaction": is_compaction,
            "project": proj_name,
            "messages": msg_count,
            "tool_calls": tool_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "models": list(models_used),
            "duration_min": round(duration, 1),
        })

        # Accumulate tokens by model for subagents
        for m in models_used:
            model_tokens[m]["input"] += input_tokens // max(len(models_used), 1)
            model_tokens[m]["output"] += output_tokens // max(len(models_used), 1)
            model_tokens[m]["cache_read"] += cache_read // max(len(models_used), 1)

    return {
        "subagents": subagents,
        "type_counts": dict(type_counts),
        "total_count": len(subagents),
        "compaction_count": sum(1 for s in subagents if s["is_compaction"]),
        "total_subagent_input_tokens": sum(s["input_tokens"] for s in subagents),
        "total_subagent_output_tokens": sum(s["output_tokens"] for s in subagents),
        "model_tokens": dict(model_tokens),
    }


def parse_all_sessions(claude_dir, tz_offset=None, since_date=None):
    """Parse all session data and return structured analytics.

    Args:
        claude_dir: Path to the .claude directory.
        tz_offset: Timezone offset in hours from UTC.
        since_date: Optional ISO date string (YYYY-MM-DD). If provided, only
                    messages on or after this date are included.
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

    # New: track models, branches, versions, thinking blocks, cost
    model_counts = defaultdict(lambda: {"msgs": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
    branch_activity = defaultdict(lambda: {"msgs": 0, "sessions": set(), "projects": set()})
    version_counts = defaultdict(int)
    thinking_count = 0
    total_tool_result_tokens = 0
    total_conversation_tokens = 0
    skill_usage = defaultdict(int)
    slash_commands = defaultdict(int)
    permission_modes = defaultdict(int)

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
        git_branch = None
        session_input_tokens = 0
        session_output_tokens = 0
        session_cache_read = 0
        session_cache_write = 0

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

                    # Track version, branch, permission mode
                    ver = d.get("version")
                    if ver:
                        version_counts[ver] += 1
                    br = d.get("gitBranch")
                    if br and br != "HEAD":
                        git_branch = br
                    pm = d.get("permissionMode")
                    if pm:
                        permission_modes[pm] += 1

                    if msg_type == "user" and ts:
                        dt = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")
                        ) + timedelta(hours=tz_offset)

                        # Skip messages before the since_date cutoff
                        if since_date and dt.strftime("%Y-%m-%d") < since_date:
                            continue

                        user_msgs += 1
                        if not entrypoint:
                            entrypoint = d.get("entrypoint")

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

                        # Track branch activity
                        if git_branch:
                            branch_activity[git_branch]["msgs"] += 1
                            branch_activity[git_branch]["sessions"].add(session_id[:8])
                            branch_activity[git_branch]["projects"].add(proj_name)

                    elif msg_type == "assistant" and ts:
                        dt = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")
                        ) + timedelta(hours=tz_offset)

                        # Skip messages before the since_date cutoff
                        if since_date and dt.strftime("%Y-%m-%d") < since_date:
                            continue

                        assistant_msgs += 1
                        timestamps.append(ts)

                        msg = d.get("message", {})
                        msg_model = None
                        msg_tools = []
                        input_tokens = 0
                        output_tokens = 0
                        cache_read_tokens = 0
                        cache_write_tokens = 0

                        if isinstance(msg, dict):
                            msg_model = msg.get("model", "")
                            if msg_model:
                                model = msg_model
                            content = msg.get("content", [])
                            if isinstance(content, list):
                                for c in content:
                                    if isinstance(c, dict):
                                        if c.get("type") == "tool_use":
                                            msg_tools.append(c.get("name", ""))
                                            tool_name = c.get("name", "")
                                            # Track MCP tool usage
                                            if tool_name.startswith("mcp__"):
                                                skill_usage[tool_name.split("__")[1]] += 1
                                            # Track slash command / skill invocations
                                            if tool_name == "Skill":
                                                skill_name = c.get("input", {}).get("skill", "unknown")
                                                if skill_name:
                                                    slash_commands[skill_name] += 1
                                        elif c.get("type") == "thinking":
                                            thinking_count += 1
                                tool_uses += len(msg_tools)
                            usage = msg.get("usage", {})
                            if usage:
                                input_tokens = usage.get("input_tokens", 0)
                                output_tokens = usage.get("output_tokens", 0)
                                cache_read_tokens = usage.get("cache_read_input_tokens", 0)
                                cache_write_tokens = usage.get("cache_creation_input_tokens", 0)

                        # Accumulate session tokens
                        session_input_tokens += input_tokens
                        session_output_tokens += output_tokens
                        session_cache_read += cache_read_tokens
                        session_cache_write += cache_write_tokens

                        # Track per-model token usage
                        norm_model = msg_model or model or "unknown"
                        model_counts[norm_model]["msgs"] += 1
                        model_counts[norm_model]["input"] += input_tokens
                        model_counts[norm_model]["output"] += output_tokens
                        model_counts[norm_model]["cache_read"] += cache_read_tokens
                        model_counts[norm_model]["cache_write"] += cache_write_tokens

                        # Track tool result vs conversation tokens
                        if msg_tools:
                            total_tool_result_tokens += output_tokens
                        else:
                            total_conversation_tokens += output_tokens

                        # Track branch activity for assistant msgs too
                        if git_branch:
                            branch_activity[git_branch]["msgs"] += 1

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
                "git_branch": git_branch,
                "input_tokens": session_input_tokens,
                "output_tokens": session_output_tokens,
                "cache_read_tokens": session_cache_read,
                "cache_write_tokens": session_cache_write,
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
                "weekday": wd, "hour": hr,
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
                "git_branch": s.get("git_branch", ""),
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
        active_secs = 120
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

    # === NEW: Model breakdown ===
    total_output = sum(v["output"] for v in model_counts.values())
    total_input = sum(v["input"] for v in model_counts.values())
    total_cache_read = sum(v["cache_read"] for v in model_counts.values())
    total_cache_write = sum(v["cache_write"] for v in model_counts.values())

    model_breakdown = []
    for raw_model, counts in sorted(model_counts.items(), key=lambda x: -x[1]["msgs"]):
        display = normalize_model_name(raw_model)
        cost_tier = match_model_cost(raw_model)
        cost = (
            counts["input"] / 1_000_000 * cost_tier["input"]
            + counts["output"] / 1_000_000 * cost_tier["output"]
            + counts["cache_read"] / 1_000_000 * cost_tier["cache_read"]
            + counts["cache_write"] / 1_000_000 * cost_tier["cache_write"]
        )
        model_breakdown.append({
            "model": raw_model,
            "display": display,
            "msgs": counts["msgs"],
            "input_tokens": counts["input"],
            "output_tokens": counts["output"],
            "cache_read_tokens": counts["cache_read"],
            "cache_write_tokens": counts["cache_write"],
            "estimated_cost": round(cost, 2),
        })

    # === NEW: Cost estimation ===
    total_cost = sum(m["estimated_cost"] for m in model_breakdown)

    # === NEW: Subagent analysis ===
    subagent_data = parse_subagents(claude_dir, tz_offset)

    # Add subagent costs
    subagent_cost = 0
    for raw_model, tokens in subagent_data["model_tokens"].items():
        cost_tier = match_model_cost(raw_model)
        subagent_cost += (
            tokens["input"] / 1_000_000 * cost_tier["input"]
            + tokens["output"] / 1_000_000 * cost_tier["output"]
            + tokens["cache_read"] / 1_000_000 * cost_tier["cache_read"]
        )
    subagent_data["estimated_cost"] = round(subagent_cost, 2)
    total_cost += subagent_cost

    # === NEW: Git branch data ===
    branch_data = sorted(
        [
            {
                "branch": br,
                "msgs": d["msgs"],
                "sessions": len(d["sessions"]),
                "projects": list(d["projects"]),
            }
            for br, d in branch_activity.items()
        ],
        key=lambda x: -x["msgs"],
    )[:20]

    # === NEW: Context efficiency ===
    total_all_output = total_output + subagent_data["total_subagent_output_tokens"]
    context_efficiency = {
        "tool_output_tokens": total_tool_result_tokens,
        "conversation_tokens": total_conversation_tokens,
        "tool_pct": round(total_tool_result_tokens / max(total_output, 1) * 100, 1),
        "conversation_pct": round(total_conversation_tokens / max(total_output, 1) * 100, 1),
        "thinking_blocks": thinking_count,
        "subagent_output_tokens": subagent_data["total_subagent_output_tokens"],
        "subagent_pct": round(subagent_data["total_subagent_output_tokens"] / max(total_all_output, 1) * 100, 1),
    }

    # === NEW: Version tracking ===
    version_data = [
        {"version": v, "count": c}
        for v, c in sorted(version_counts.items(), key=lambda x: -x[1])[:10]
    ]

    # === NEW: Skill/MCP usage ===
    skill_data = [
        {"skill": s, "count": c}
        for s, c in sorted(skill_usage.items(), key=lambda x: -x[1])[:15]
    ]

    # === NEW: Slash command usage ===
    slash_command_data = [
        {"command": cmd, "count": c}
        for cmd, c in sorted(slash_commands.items(), key=lambda x: -x[1])[:15]
    ]

    # Config
    config = parse_config(claude_dir)

    summary = {
        "total_sessions": len(sessions_meta),
        "total_user_msgs": len(user_messages),
        "total_assistant_msgs": len(asst_messages),
        "total_tool_calls": sum(
            len(m.get("tool_uses", [])) for m in asst_messages
        ),
        "total_output_tokens": total_output,
        "total_input_tokens": total_input,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_write_tokens": total_cache_write,
        "date_range_start": all_dates[0] if all_dates else "",
        "date_range_end": all_dates[-1] if all_dates else "",
        "since_date": since_date or "",
        "unique_projects": len(project_stats),
        "unique_tools": len(tool_counts),
        "avg_session_duration": round(
            sum(s["duration_min"] for s in session_durations)
            / max(len(session_durations), 1),
            1,
        ),
        "tz_offset": tz_offset,
        "tz_label": f"UTC{tz_offset:+d}",
        "estimated_cost": round(total_cost, 2),
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
        # NEW data
        "models": model_breakdown,
        "subagents": subagent_data,
        "branches": branch_data,
        "context_efficiency": context_efficiency,
        "versions": version_data,
        "skills": skill_data,
        "slash_commands": slash_command_data,
        "permission_modes": dict(permission_modes),
        "config": config,
    }

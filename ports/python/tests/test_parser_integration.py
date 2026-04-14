"""Integration tests for parse_all_sessions with synthetic JSONL fixtures."""

import json
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from claude_analytics.parser import parse_all_sessions


def _ts(dt: datetime) -> str:
    """Format a datetime as an ISO timestamp string with Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _user_msg(timestamp: str, text: str, **extra) -> dict:
    """Build a minimal user-type JSONL line."""
    d = {
        "type": "user",
        "timestamp": timestamp,
        "message": {"role": "user", "content": text},
    }
    d.update(extra)
    return d


def _assistant_msg(
    timestamp: str,
    text: str = "Sure, I can help.",
    model: str = "claude-sonnet-4-20250514",
    tool_uses: list[dict] | None = None,
    input_tokens: int = 100,
    output_tokens: int = 200,
    cache_read: int = 0,
    cache_write: int = 0,
    **extra,
) -> dict:
    """Build a minimal assistant-type JSONL line."""
    content = []
    if text:
        content.append({"type": "text", "text": text})
    if tool_uses:
        for tu in tool_uses:
            content.append({"type": "tool_use", "name": tu.get("name", "Read"), "input": tu.get("input", {})})
    d = {
        "type": "assistant",
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "model": model,
            "content": content,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
            },
        },
    }
    d.update(extra)
    return d


def _write_session(base_dir: Path, project: str, session_id: str, messages: list[dict]):
    """Write a list of message dicts as JSONL into the correct directory structure."""
    session_dir = base_dir / "projects" / project
    session_dir.mkdir(parents=True, exist_ok=True)
    filepath = session_dir / f"{session_id}.jsonl"
    with open(filepath, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return filepath


class TestParseAllSessionsBasic(unittest.TestCase):
    """Basic parsing: a minimal valid session produces expected summary structure."""

    def test_minimal_session_returns_expected_keys(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
            t1 = t0 + timedelta(minutes=5)
            messages = [
                _user_msg(_ts(t0), "Hello, help me with this code"),
                _assistant_msg(_ts(t1), "Sure, I can help with that."),
            ]
            _write_session(base, "my-project", "sess-001", messages)

            result = parse_all_sessions(base, tz_offset=0)

            # Top-level keys
            for key in (
                "dashboard", "drilldown", "analysis", "prompts", "work_days",
                "models", "subagents", "branches", "context_efficiency",
                "versions", "skills", "slash_commands", "permission_modes", "config",
            ):
                self.assertIn(key, result, f"Missing top-level key: {key}")

            # Dashboard sub-keys
            dash = result["dashboard"]
            for key in (
                "summary", "daily", "heatmap", "projects", "tools",
                "hourly", "sessions", "weekly", "efficiency",
            ):
                self.assertIn(key, dash, f"Missing dashboard key: {key}")

    def test_minimal_session_summary_counts(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
            t1 = t0 + timedelta(minutes=5)
            messages = [
                _user_msg(_ts(t0), "Hello, help me with this code"),
                _assistant_msg(_ts(t1), "Sure, I can help."),
            ]
            _write_session(base, "my-project", "sess-001", messages)

            result = parse_all_sessions(base, tz_offset=0)
            summary = result["dashboard"]["summary"]

            self.assertEqual(summary["total_sessions"], 1)
            self.assertEqual(summary["total_user_msgs"], 1)
            self.assertEqual(summary["total_assistant_msgs"], 1)
            self.assertEqual(summary["unique_projects"], 1)

    def test_prompt_text_and_category_captured(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
            t1 = t0 + timedelta(minutes=1)
            messages = [
                _user_msg(_ts(t0), "fix the login bug in auth module"),
                _assistant_msg(_ts(t1), "I found the bug."),
            ]
            _write_session(base, "my-project", "sess-002", messages)

            result = parse_all_sessions(base, tz_offset=0)
            prompts = result["prompts"]

            self.assertEqual(len(prompts), 1)
            self.assertIn("fix the login bug", prompts[0]["text"])
            self.assertEqual(prompts[0]["category"], "debugging")


class TestSinceDateFiltering(unittest.TestCase):
    """Sessions before the since_date are excluded."""

    def test_since_date_excludes_old_messages(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_t0 = datetime(2025, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
            old_t1 = old_t0 + timedelta(minutes=1)
            new_t0 = datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
            new_t1 = new_t0 + timedelta(minutes=1)

            messages = [
                _user_msg(_ts(old_t0), "old prompt one"),
                _assistant_msg(_ts(old_t1), "old response"),
                _user_msg(_ts(new_t0), "new prompt two"),
                _assistant_msg(_ts(new_t1), "new response"),
            ]
            _write_session(base, "my-project", "sess-003", messages)

            result = parse_all_sessions(base, tz_offset=0, since_date="2025-06-01")
            summary = result["dashboard"]["summary"]

            self.assertEqual(summary["total_user_msgs"], 1)
            self.assertEqual(summary["since_date"], "2025-06-01")

    def test_since_date_none_includes_all(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
            t1 = t0 + timedelta(minutes=1)
            t2 = datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
            t3 = t2 + timedelta(minutes=1)

            messages = [
                _user_msg(_ts(t0), "prompt one"),
                _assistant_msg(_ts(t1), "response one"),
                _user_msg(_ts(t2), "prompt two"),
                _assistant_msg(_ts(t3), "response two"),
            ]
            _write_session(base, "my-project", "sess-004", messages)

            result = parse_all_sessions(base, tz_offset=0)
            self.assertEqual(result["dashboard"]["summary"]["total_user_msgs"], 2)


class TestMultipleSessions(unittest.TestCase):
    """Multiple sessions: counts, durations, daily aggregation."""

    def test_two_sessions_counted(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
            t1 = t0 + timedelta(minutes=10)

            sess1 = [
                _user_msg(_ts(t0), "session one prompt"),
                _assistant_msg(_ts(t0 + timedelta(minutes=1)), "resp 1"),
            ]
            sess2 = [
                _user_msg(_ts(t0 + timedelta(hours=2)), "session two prompt"),
                _assistant_msg(_ts(t1 + timedelta(hours=2)), "resp 2"),
            ]
            _write_session(base, "proj-a", "sess-a01", sess1)
            _write_session(base, "proj-a", "sess-b02", sess2)

            result = parse_all_sessions(base, tz_offset=0)
            summary = result["dashboard"]["summary"]

            self.assertEqual(summary["total_sessions"], 2)
            self.assertEqual(summary["total_user_msgs"], 2)

    def test_sessions_across_projects(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            sess1 = [
                _user_msg(_ts(t0), "project alpha prompt"),
                _assistant_msg(_ts(t0 + timedelta(minutes=1)), "alpha resp"),
            ]
            sess2 = [
                _user_msg(_ts(t0 + timedelta(hours=1)), "project beta prompt"),
                _assistant_msg(_ts(t0 + timedelta(hours=1, minutes=1)), "beta resp"),
            ]
            _write_session(base, "alpha", "sess-a01", sess1)
            _write_session(base, "beta", "sess-b01", sess2)

            result = parse_all_sessions(base, tz_offset=0)
            self.assertEqual(result["dashboard"]["summary"]["unique_projects"], 2)

    def test_daily_aggregation(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            day1 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
            day2 = datetime(2025, 6, 2, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(day1), "day one first"),
                _assistant_msg(_ts(day1 + timedelta(minutes=1)), "resp"),
                _user_msg(_ts(day1 + timedelta(minutes=5)), "day one second"),
                _assistant_msg(_ts(day1 + timedelta(minutes=6)), "resp"),
                _user_msg(_ts(day2), "day two only"),
                _assistant_msg(_ts(day2 + timedelta(minutes=1)), "resp"),
            ]
            _write_session(base, "my-proj", "sess-daily", messages)

            result = parse_all_sessions(base, tz_offset=0)
            daily = result["dashboard"]["daily"]

            day1_entry = next(d for d in daily if d["date"] == "2025-06-01")
            day2_entry = next(d for d in daily if d["date"] == "2025-06-02")

            self.assertEqual(day1_entry["user_msgs"], 2)
            self.assertEqual(day2_entry["user_msgs"], 1)


class TestModelTracking(unittest.TestCase):
    """Different models are counted and costs estimated."""

    def test_model_breakdown_multiple_models(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "prompt for sonnet"),
                _assistant_msg(
                    _ts(t0 + timedelta(minutes=1)), "sonnet response",
                    model="claude-sonnet-4-20250514",
                    input_tokens=1000, output_tokens=2000,
                ),
                _user_msg(_ts(t0 + timedelta(minutes=2)), "prompt for opus"),
                _assistant_msg(
                    _ts(t0 + timedelta(minutes=3)), "opus response",
                    model="claude-opus-4-20250514",
                    input_tokens=500, output_tokens=1000,
                ),
            ]
            _write_session(base, "my-proj", "sess-model", messages)

            result = parse_all_sessions(base, tz_offset=0)
            models = result["models"]

            model_names = {m["model"] for m in models}
            self.assertIn("claude-sonnet-4-20250514", model_names)
            self.assertIn("claude-opus-4-20250514", model_names)

    def test_cost_estimation_positive(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "create a new REST endpoint"),
                _assistant_msg(
                    _ts(t0 + timedelta(minutes=1)), "Here is the code.",
                    model="claude-sonnet-4-20250514",
                    input_tokens=10000, output_tokens=5000,
                ),
            ]
            _write_session(base, "my-proj", "sess-cost", messages)

            result = parse_all_sessions(base, tz_offset=0)
            self.assertGreater(result["dashboard"]["summary"]["estimated_cost"], 0)

    def test_token_counts_accumulated(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "first prompt"),
                _assistant_msg(
                    _ts(t0 + timedelta(minutes=1)), "resp 1",
                    input_tokens=100, output_tokens=200,
                ),
                _user_msg(_ts(t0 + timedelta(minutes=2)), "second prompt"),
                _assistant_msg(
                    _ts(t0 + timedelta(minutes=3)), "resp 2",
                    input_tokens=300, output_tokens=400,
                ),
            ]
            _write_session(base, "my-proj", "sess-tokens", messages)

            result = parse_all_sessions(base, tz_offset=0)
            summary = result["dashboard"]["summary"]
            self.assertEqual(summary["total_input_tokens"], 400)
            self.assertEqual(summary["total_output_tokens"], 600)


class TestToolUsageExtraction(unittest.TestCase):
    """Tool use blocks are counted correctly."""

    def test_tool_uses_counted(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "read the config file please"),
                _assistant_msg(
                    _ts(t0 + timedelta(minutes=1)), "Let me read that.",
                    tool_uses=[
                        {"name": "Read", "input": {"path": "/etc/config"}},
                        {"name": "Bash", "input": {"command": "ls"}},
                    ],
                ),
            ]
            _write_session(base, "my-proj", "sess-tools", messages)

            result = parse_all_sessions(base, tz_offset=0)
            summary = result["dashboard"]["summary"]
            self.assertEqual(summary["total_tool_calls"], 2)

            tools = result["dashboard"]["tools"]
            tool_names = {t["tool"] for t in tools}
            self.assertIn("Read", tool_names)
            self.assertIn("Bash", tool_names)

    def test_skill_invocation_tracked(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "review this PR"),
                _assistant_msg(
                    _ts(t0 + timedelta(minutes=1)), "Invoking skill.",
                    tool_uses=[
                        {"name": "Skill", "input": {"skill": "review"}},
                    ],
                ),
            ]
            _write_session(base, "my-proj", "sess-skill", messages)

            result = parse_all_sessions(base, tz_offset=0)
            slash = result["slash_commands"]
            self.assertTrue(any(s["command"] == "review" for s in slash))


class TestPromptCategorization(unittest.TestCase):
    """Prompts get categorized correctly in context of full parse."""

    def test_multiple_categories_in_session(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "fix the login bug"),
                _assistant_msg(_ts(t0 + timedelta(minutes=1)), "Fixed."),
                _user_msg(_ts(t0 + timedelta(minutes=2)), "create a new user page"),
                _assistant_msg(_ts(t0 + timedelta(minutes=3)), "Created."),
                _user_msg(_ts(t0 + timedelta(minutes=4)), "how does the auth work?"),
                _assistant_msg(_ts(t0 + timedelta(minutes=5)), "It works by..."),
            ]
            _write_session(base, "my-proj", "sess-cats", messages)

            result = parse_all_sessions(base, tz_offset=0)
            categories = {p["category"] for p in result["prompts"]}
            self.assertIn("debugging", categories)
            self.assertIn("building", categories)
            self.assertIn("question", categories)

    def test_analysis_categories_sum_to_total(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = []
            for i in range(6):
                dt = t0 + timedelta(minutes=i * 2)
                messages.append(_user_msg(_ts(dt), f"implement feature number {i} now"))
                messages.append(_assistant_msg(_ts(dt + timedelta(minutes=1)), f"Done {i}."))
            _write_session(base, "my-proj", "sess-sum", messages)

            result = parse_all_sessions(base, tz_offset=0)
            analysis = result["analysis"]
            cat_total = sum(c["count"] for c in analysis["categories"])
            self.assertEqual(cat_total, analysis["total_prompts"])


class TestEmptyAndCorruptFiles(unittest.TestCase):
    """Empty/corrupt session files are handled gracefully."""

    def test_empty_file_no_crash(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            # Write an empty JSONL
            proj_dir = base / "projects" / "empty-proj"
            proj_dir.mkdir(parents=True)
            (proj_dir / "sess-empty.jsonl").write_text("")

            # Must have at least one valid session for parse_all_sessions
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
            messages = [
                _user_msg(_ts(t0), "a valid prompt here"),
                _assistant_msg(_ts(t0 + timedelta(minutes=1)), "ok"),
            ]
            _write_session(base, "good-proj", "sess-good", messages)

            result = parse_all_sessions(base, tz_offset=0)
            self.assertEqual(result["dashboard"]["summary"]["total_user_msgs"], 1)

    def test_corrupt_json_lines_skipped(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            proj_dir = base / "projects" / "corrupt-proj"
            proj_dir.mkdir(parents=True)
            filepath = proj_dir / "sess-corrupt.jsonl"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("{not valid json}\n")
                f.write("totally broken line\n")
                f.write(json.dumps(_user_msg(_ts(t0), "valid prompt after corrupt lines")) + "\n")
                f.write(json.dumps(_assistant_msg(_ts(t0 + timedelta(minutes=1)), "ok")) + "\n")

            result = parse_all_sessions(base, tz_offset=0)
            self.assertEqual(result["dashboard"]["summary"]["total_user_msgs"], 1)

    def test_no_sessions_raises_error(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "projects").mkdir(parents=True)
            with self.assertRaises(ValueError):
                parse_all_sessions(base, tz_offset=0)


class TestSingleMessageSession(unittest.TestCase):
    """Edge case: session with only one message."""

    def test_single_user_message_only(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
            messages = [
                _user_msg(_ts(t0), "just a single prompt with no response"),
            ]
            _write_session(base, "my-proj", "sess-single", messages)

            result = parse_all_sessions(base, tz_offset=0)
            summary = result["dashboard"]["summary"]
            self.assertEqual(summary["total_user_msgs"], 1)
            self.assertEqual(summary["total_assistant_msgs"], 0)
            self.assertEqual(summary["total_sessions"], 1)


class TestTimezoneHandling(unittest.TestCase):
    """Timezone offset is applied to message dates correctly."""

    def test_positive_offset_shifts_date(self):
        """A message at 23:00 UTC should appear on the next date with +2 offset."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            # 23:00 UTC on June 1 -> 01:00 June 2 at UTC+2
            t0 = datetime(2025, 6, 1, 23, 0, 0, tzinfo=timezone.utc)
            t1 = t0 + timedelta(minutes=5)
            messages = [
                _user_msg(_ts(t0), "late night prompt testing tz"),
                _assistant_msg(_ts(t1), "response"),
            ]
            _write_session(base, "tz-proj", "sess-tz", messages)

            result = parse_all_sessions(base, tz_offset=2)
            prompts = result["prompts"]
            self.assertEqual(len(prompts), 1)
            self.assertEqual(prompts[0]["date"], "2025-06-02")
            self.assertEqual(prompts[0]["hour"], 1)

    def test_negative_offset_shifts_date(self):
        """A message at 01:00 UTC should appear on the previous date with -5 offset."""
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            # 01:00 UTC on June 2 -> 20:00 June 1 at UTC-5
            t0 = datetime(2025, 6, 2, 1, 0, 0, tzinfo=timezone.utc)
            t1 = t0 + timedelta(minutes=5)
            messages = [
                _user_msg(_ts(t0), "early morning utc prompt for tz test"),
                _assistant_msg(_ts(t1), "response"),
            ]
            _write_session(base, "tz-proj", "sess-tz2", messages)

            result = parse_all_sessions(base, tz_offset=-5)
            prompts = result["prompts"]
            self.assertEqual(len(prompts), 1)
            self.assertEqual(prompts[0]["date"], "2025-06-01")
            self.assertEqual(prompts[0]["hour"], 20)


class TestSessionDuration(unittest.TestCase):
    """Session duration is calculated from first to last timestamp."""

    def test_duration_calculation(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
            t1 = t0 + timedelta(minutes=30)

            messages = [
                _user_msg(_ts(t0), "start of session prompt"),
                _assistant_msg(_ts(t0 + timedelta(minutes=1)), "resp 1"),
                _user_msg(_ts(t1 - timedelta(minutes=1)), "end of session prompt"),
                _assistant_msg(_ts(t1), "resp 2"),
            ]
            _write_session(base, "my-proj", "sess-dur", messages)

            result = parse_all_sessions(base, tz_offset=0)
            sessions = result["dashboard"]["sessions"]
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["duration_min"], 30.0)


class TestVersionAndBranchTracking(unittest.TestCase):
    """Version and git branch metadata is tracked."""

    def test_version_tracked(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "prompt with version", version="1.0.5"),
                _assistant_msg(_ts(t0 + timedelta(minutes=1)), "resp"),
            ]
            _write_session(base, "my-proj", "sess-ver", messages)

            result = parse_all_sessions(base, tz_offset=0)
            versions = result["versions"]
            self.assertTrue(any(v["version"] == "1.0.5" for v in versions))

    def test_branch_tracked(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "prompt on feature branch", gitBranch="feature/login"),
                _assistant_msg(_ts(t0 + timedelta(minutes=1)), "resp", gitBranch="feature/login"),
            ]
            _write_session(base, "my-proj", "sess-branch", messages)

            result = parse_all_sessions(base, tz_offset=0)
            branches = result["branches"]
            self.assertTrue(any(b["branch"] == "feature/login" for b in branches))

    def test_permission_mode_tracked(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "prompt with permission mode", permissionMode="auto-accept"),
                _assistant_msg(_ts(t0 + timedelta(minutes=1)), "resp"),
            ]
            _write_session(base, "my-proj", "sess-perm", messages)

            result = parse_all_sessions(base, tz_offset=0)
            self.assertIn("auto-accept", result["permission_modes"])


class TestWorkDays(unittest.TestCase):
    """Work day spans are calculated from user message timestamps."""

    def test_work_day_span(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 9, 0, 0, tzinfo=timezone.utc)

            messages = [
                _user_msg(_ts(t0), "morning prompt for work day test"),
                _assistant_msg(_ts(t0 + timedelta(minutes=1)), "resp"),
                _user_msg(_ts(t0 + timedelta(hours=3)), "afternoon prompt for span"),
                _assistant_msg(_ts(t0 + timedelta(hours=3, minutes=1)), "resp"),
            ]
            _write_session(base, "my-proj", "sess-wd", messages)

            result = parse_all_sessions(base, tz_offset=0)
            work_days = result["work_days"]
            self.assertEqual(len(work_days), 1)
            self.assertEqual(work_days[0]["date"], "2025-06-01")
            self.assertEqual(work_days[0]["first"], "09:00")
            self.assertEqual(work_days[0]["last"], "12:00")
            self.assertEqual(work_days[0]["span_hrs"], 3.0)
            self.assertEqual(work_days[0]["prompts"], 2)


class TestThinkingBlocks(unittest.TestCase):
    """Thinking blocks in assistant messages are counted."""

    def test_thinking_block_counted(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            t0 = datetime(2025, 6, 1, 10, 0, 0, tzinfo=timezone.utc)

            # Build assistant message with a thinking block manually
            asst = {
                "type": "assistant",
                "timestamp": _ts(t0 + timedelta(minutes=1)),
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-20250514",
                    "content": [
                        {"type": "thinking", "thinking": "Let me think about this..."},
                        {"type": "text", "text": "Here is my answer."},
                    ],
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 200,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                },
            }

            messages = [
                _user_msg(_ts(t0), "explain how the auth system works"),
                asst,
            ]
            _write_session(base, "my-proj", "sess-think", messages)

            result = parse_all_sessions(base, tz_offset=0)
            self.assertGreaterEqual(result["context_efficiency"]["thinking_blocks"], 1)


if __name__ == "__main__":
    unittest.main()

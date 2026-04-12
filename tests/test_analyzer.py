"""Tests for claude_analytics.analyzer functions."""

import unittest

from claude_analytics.analyzer import (
    find_example_prompts,
    find_short_prompts,
    get_heuristic_recommendations,
)


class TestFindShortPrompts(unittest.TestCase):
    """Tests for find_short_prompts()."""

    def test_returns_short_prompts(self):
        prompts = [
            {"text": "fix it", "full_length": 6},
            {"text": "ok do that thing", "full_length": 16},
            {"text": "This is a much longer prompt that exceeds the limit", "full_length": 200},
        ]
        result = find_short_prompts(prompts, max_chars=50, max_count=5)
        self.assertEqual(len(result), 2)
        self.assertIn("fix it", result)
        self.assertIn("ok do that thing", result)

    def test_skips_very_short_text(self):
        prompts = [
            {"text": "ok", "full_length": 2},   # stripped length <= 3 -> excluded
            {"text": "yes", "full_length": 3},   # stripped length == 3 -> excluded
            {"text": "hello there", "full_length": 11},
        ]
        result = find_short_prompts(prompts, max_chars=50, max_count=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "hello there")

    def test_limits_count(self):
        prompts = [{"text": f"prompt number {i}", "full_length": 15} for i in range(20)]
        result = find_short_prompts(prompts, max_chars=50, max_count=3)
        self.assertLessEqual(len(result), 3)

    def test_empty_input(self):
        result = find_short_prompts([], max_chars=50, max_count=5)
        self.assertEqual(result, [])


class TestFindExamplePrompts(unittest.TestCase):
    """Tests for find_example_prompts()."""

    def test_filters_by_category(self):
        prompts = [
            {"text": "fix the login bug in auth", "category": "debugging", "full_length": 25},
            {"text": "create a new user page now", "category": "building", "full_length": 26},
            {"text": "there is an error in the payment service", "category": "debugging", "full_length": 40},
        ]
        result = find_example_prompts(prompts, "debugging")
        self.assertEqual(len(result), 2)
        self.assertTrue(all("debugging" not in r for r in result))  # returns text, not dicts

    def test_skips_short_text(self):
        prompts = [
            {"text": "fix bug", "category": "debugging", "full_length": 7},  # len <= 15 -> excluded
            {"text": "fix the authentication bug", "category": "debugging", "full_length": 25},
        ]
        result = find_example_prompts(prompts, "debugging")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], "fix the authentication bug")

    def test_respects_max_count(self):
        prompts = [
            {"text": f"debugging prompt number {i} here", "category": "debugging", "full_length": 30 + i}
            for i in range(10)
        ]
        result = find_example_prompts(prompts, "debugging", max_count=2)
        self.assertEqual(len(result), 2)

    def test_empty_category(self):
        prompts = [
            {"text": "create a new user page now", "category": "building", "full_length": 26},
        ]
        result = find_example_prompts(prompts, "debugging")
        self.assertEqual(result, [])

    def test_sorts_by_full_length(self):
        prompts = [
            {"text": "a longer debugging prompt text here", "category": "debugging", "full_length": 100},
            {"text": "short debug prompt text", "category": "debugging", "full_length": 22},
        ]
        result = find_example_prompts(prompts, "debugging")
        # Shorter full_length should come first
        self.assertEqual(result[0], "short debug prompt text")


class TestGetHeuristicRecommendations(unittest.TestCase):
    """Tests for get_heuristic_recommendations()."""

    def _make_analysis(self, categories=None, length_buckets=None, total=100, avg_length=80):
        """Helper to build a minimal analysis dict."""
        cats = categories or []
        buckets = length_buckets or []
        return {
            "total_prompts": total,
            "avg_length": avg_length,
            "categories": cats,
            "length_buckets": buckets,
        }

    def _make_summary(self, total_user_msgs=100, total_sessions=10):
        return {
            "total_user_msgs": total_user_msgs,
            "total_sessions": total_sessions,
        }

    def test_high_debugging_triggers_recommendation(self):
        analysis = self._make_analysis(
            categories=[
                {"cat": "debugging", "pct": 25},
                {"cat": "testing", "pct": 2},
                {"cat": "building", "pct": 30},
                {"cat": "question", "pct": 5},
                {"cat": "refactoring", "pct": 1},
                {"cat": "confirmation", "pct": 5},
                {"cat": "editing", "pct": 10},
            ],
            length_buckets=[
                {"bucket": "micro (<20)", "pct": 5},
                {"bucket": "short (20-50)", "pct": 10},
            ],
        )
        summary = self._make_summary()
        recs = get_heuristic_recommendations(analysis, summary, work_days=[])
        titles = [r["title"] for r in recs]
        self.assertIn("Reduce debugging cycles", titles)

    def test_low_testing_triggers_recommendation(self):
        analysis = self._make_analysis(
            categories=[
                {"cat": "debugging", "pct": 5},
                {"cat": "testing", "pct": 2},
                {"cat": "building", "pct": 30},
                {"cat": "question", "pct": 5},
                {"cat": "refactoring", "pct": 1},
                {"cat": "confirmation", "pct": 5},
                {"cat": "editing", "pct": 10},
            ],
            length_buckets=[
                {"bucket": "micro (<20)", "pct": 5},
                {"bucket": "short (20-50)", "pct": 10},
            ],
        )
        summary = self._make_summary()
        recs = get_heuristic_recommendations(analysis, summary, work_days=[])
        titles = [r["title"] for r in recs]
        self.assertIn("Ask for tests alongside features", titles)

    def test_debugging_severity_high_when_above_20(self):
        analysis = self._make_analysis(
            categories=[
                {"cat": "debugging", "pct": 25},
                {"cat": "testing", "pct": 10},
                {"cat": "building", "pct": 30},
                {"cat": "question", "pct": 15},
                {"cat": "refactoring", "pct": 10},
                {"cat": "confirmation", "pct": 5},
                {"cat": "editing", "pct": 5},
            ],
            length_buckets=[
                {"bucket": "micro (<20)", "pct": 5},
                {"bucket": "short (20-50)", "pct": 5},
            ],
        )
        summary = self._make_summary()
        recs = get_heuristic_recommendations(analysis, summary, work_days=[])
        debug_rec = next(r for r in recs if r["title"] == "Reduce debugging cycles")
        self.assertEqual(debug_rec["severity"], "high")

    def test_debugging_severity_medium_when_between_12_and_20(self):
        analysis = self._make_analysis(
            categories=[
                {"cat": "debugging", "pct": 15},
                {"cat": "testing", "pct": 10},
                {"cat": "building", "pct": 30},
                {"cat": "question", "pct": 15},
                {"cat": "refactoring", "pct": 10},
                {"cat": "confirmation", "pct": 5},
                {"cat": "editing", "pct": 5},
            ],
            length_buckets=[
                {"bucket": "micro (<20)", "pct": 5},
                {"bucket": "short (20-50)", "pct": 5},
            ],
        )
        summary = self._make_summary()
        recs = get_heuristic_recommendations(analysis, summary, work_days=[])
        debug_rec = next(r for r in recs if r["title"] == "Reduce debugging cycles")
        self.assertEqual(debug_rec["severity"], "medium")

    def test_no_debugging_rec_when_below_threshold(self):
        analysis = self._make_analysis(
            categories=[
                {"cat": "debugging", "pct": 5},
                {"cat": "testing", "pct": 15},
                {"cat": "building", "pct": 30},
                {"cat": "question", "pct": 15},
                {"cat": "refactoring", "pct": 10},
                {"cat": "confirmation", "pct": 5},
                {"cat": "editing", "pct": 5},
            ],
            length_buckets=[
                {"bucket": "micro (<20)", "pct": 5},
                {"bucket": "short (20-50)", "pct": 5},
            ],
        )
        summary = self._make_summary()
        recs = get_heuristic_recommendations(analysis, summary, work_days=[])
        titles = [r["title"] for r in recs]
        self.assertNotIn("Reduce debugging cycles", titles)

    def test_recommendations_have_required_fields(self):
        analysis = self._make_analysis(
            categories=[
                {"cat": "debugging", "pct": 25},
                {"cat": "testing", "pct": 2},
                {"cat": "building", "pct": 30},
                {"cat": "question", "pct": 5},
                {"cat": "refactoring", "pct": 1},
                {"cat": "confirmation", "pct": 5},
                {"cat": "editing", "pct": 10},
            ],
            length_buckets=[
                {"bucket": "micro (<20)", "pct": 5},
                {"bucket": "short (20-50)", "pct": 10},
            ],
        )
        summary = self._make_summary()
        recs = get_heuristic_recommendations(analysis, summary, work_days=[])
        for rec in recs:
            self.assertIn("title", rec)
            self.assertIn("severity", rec)
            self.assertIn("body", rec)
            self.assertIn("metric", rec)
            self.assertIn("example", rec)
            self.assertIn(rec["severity"], ("low", "medium", "high"))


if __name__ == "__main__":
    unittest.main()

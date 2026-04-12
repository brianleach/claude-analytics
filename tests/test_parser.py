"""Tests for claude_analytics.parser functions."""

import unittest
from pathlib import Path
from unittest.mock import patch

from claude_analytics.parser import (
    categorize_prompt,
    clean_project_name,
    length_bucket,
    match_model_cost,
    normalize_model_name,
    MODEL_COSTS,
)


class TestCategorizePrompt(unittest.TestCase):
    """Tests for categorize_prompt()."""

    # --- micro ---
    def test_micro_very_short(self):
        self.assertEqual(categorize_prompt("yes"), "micro")

    def test_micro_two_chars(self):
        self.assertEqual(categorize_prompt("ok"), "micro")

    def test_micro_single_char(self):
        self.assertEqual(categorize_prompt("y"), "micro")

    # --- confirmation ---
    def test_confirmation_yes(self):
        # Confirmation regex requires exact match; "sure" is only 4 chars (micro).
        # Use a 5+ char confirmation word.
        self.assertEqual(categorize_prompt("do it"), "confirmation")

    def test_confirmation_go_ahead(self):
        self.assertEqual(categorize_prompt("go ahead"), "confirmation")

    def test_confirmation_ship_it(self):
        self.assertEqual(categorize_prompt("ship it"), "confirmation")

    def test_confirmation_lgtm(self):
        self.assertEqual(categorize_prompt("lgtm"), "micro")  # lgtm is 4 chars -> micro

    def test_confirmation_looks_good(self):
        self.assertEqual(categorize_prompt("looks good"), "confirmation")

    def test_confirmation_proceed(self):
        self.assertEqual(categorize_prompt("proceed"), "confirmation")

    # --- debugging ---
    def test_debugging_fix_bug(self):
        self.assertEqual(categorize_prompt("fix the login bug"), "debugging")

    def test_debugging_error_in_auth(self):
        self.assertEqual(categorize_prompt("there's an error in auth"), "debugging")

    def test_debugging_crash(self):
        # "crashing" doesn't match \bcrash\b, use exact word
        self.assertEqual(categorize_prompt("the server crash is back"), "debugging")

    def test_debugging_not_working(self):
        self.assertEqual(categorize_prompt("the form is not working"), "debugging")

    # --- building ---
    def test_building_create(self):
        self.assertEqual(categorize_prompt("create a new user page"), "building")

    def test_building_implement(self):
        self.assertEqual(categorize_prompt("implement the search feature"), "building")

    def test_building_add_feature(self):
        self.assertEqual(categorize_prompt("add a sidebar navigation"), "building")

    # --- refactoring ---
    def test_refactoring_refactor(self):
        self.assertEqual(categorize_prompt("refactor the auth module"), "refactoring")

    def test_refactoring_simplify(self):
        self.assertEqual(categorize_prompt("simplify the payment logic"), "refactoring")

    def test_refactoring_extract(self):
        self.assertEqual(categorize_prompt("extract the validation into a util"), "refactoring")

    # --- question ---
    def test_question_how(self):
        self.assertEqual(categorize_prompt("how does the auth work?"), "question")

    def test_question_what(self):
        self.assertEqual(categorize_prompt("what is this function?"), "question")

    def test_question_why(self):
        # "null" triggers debugging before question check; use a question without debug words
        self.assertEqual(categorize_prompt("why does this return early?"), "question")

    # --- review ---
    def test_review_pr(self):
        self.assertEqual(categorize_prompt("review this PR please"), "review")

    def test_review_check(self):
        # "build" triggers "building" before "review"; avoid building keywords
        self.assertEqual(categorize_prompt("check the output of the server"), "review")

    def test_review_show_me(self):
        self.assertEqual(categorize_prompt("show me the current config"), "review")

    # --- editing ---
    def test_editing_update(self):
        self.assertEqual(categorize_prompt("update the config file"), "editing")

    def test_editing_change_color(self):
        self.assertEqual(categorize_prompt("change the color to blue"), "editing")

    def test_editing_remove(self):
        self.assertEqual(categorize_prompt("remove the deprecated endpoint"), "editing")

    # --- testing ---
    def test_testing_run_tests(self):
        # "write" triggers "building" before "testing"; use a prompt without building keywords
        self.assertEqual(categorize_prompt("run the test suite for auth"), "testing")

    def test_testing_coverage(self):
        # "check" triggers "review" before "testing"; avoid review keywords
        self.assertEqual(categorize_prompt("improve test coverage for auth"), "testing")

    # --- git_ops ---
    def test_git_ops_commit_push(self):
        self.assertEqual(categorize_prompt("commit and push the changes"), "git_ops")

    def test_git_ops_pull_request(self):
        # "create" triggers "building" before "git_ops"; use phrasing without building keywords
        self.assertEqual(categorize_prompt("open a pull request for this"), "git_ops")

    def test_git_ops_merge(self):
        self.assertEqual(categorize_prompt("merge the feature branch"), "git_ops")

    # --- brief ---
    def test_brief_short_generic(self):
        result = categorize_prompt("do the thing now")
        self.assertEqual(result, "brief")

    # --- detailed ---
    def test_detailed_long_generic(self):
        # Avoid keywords from earlier categories (look at -> "review" via "look at")
        text = "i think we should consider the overall architecture of the system and how the components interact with each other"
        result = categorize_prompt(text)
        self.assertEqual(result, "detailed")

    # --- false positives ---
    def test_false_positive_prefix_not_debugging(self):
        # "prefix" contains "fix" but should NOT trigger debugging because \bfix\b won't match
        self.assertNotEqual(categorize_prompt("set the prefix for the logger"), "debugging")

    def test_false_positive_address_not_building(self):
        # "address" contains "add" but \badd\b should not match inside "address"
        self.assertNotEqual(categorize_prompt("the address field is empty"), "building")

    def test_false_positive_additionally_not_building(self):
        # "additionally" contains "add" but word boundary should prevent match
        self.assertNotEqual(categorize_prompt("additionally the page loads slow"), "building")

    def test_false_positive_fixed_width_not_debugging(self):
        # "fixed-width" — "fixed" doesn't match "fix" as a standalone word
        self.assertNotEqual(categorize_prompt("use a fixed-width font here"), "debugging")


class TestMatchModelCost(unittest.TestCase):
    """Tests for match_model_cost()."""

    def test_opus_model(self):
        result = match_model_cost("claude-opus-4-20250514")
        self.assertEqual(result, MODEL_COSTS["claude-opus-4"])

    def test_sonnet_model(self):
        result = match_model_cost("claude-sonnet-4-20250514")
        self.assertEqual(result, MODEL_COSTS["claude-sonnet-4"])

    def test_haiku_model(self):
        result = match_model_cost("claude-haiku-4-5-20251001")
        self.assertEqual(result, MODEL_COSTS["claude-haiku-4"])

    def test_empty_string_defaults_to_sonnet(self):
        result = match_model_cost("")
        self.assertEqual(result, MODEL_COSTS["claude-sonnet-4"])

    def test_none_defaults_to_sonnet(self):
        result = match_model_cost(None)
        self.assertEqual(result, MODEL_COSTS["claude-sonnet-4"])

    def test_unknown_model_defaults_to_sonnet(self):
        result = match_model_cost("some-unknown-model")
        self.assertEqual(result, MODEL_COSTS["claude-sonnet-4"])


class TestCleanProjectName(unittest.TestCase):
    """Tests for clean_project_name()."""

    def test_strips_home_prefix(self):
        home = str(Path.home()).replace("/", "-").replace("\\", "-")
        if home.startswith("-"):
            home = home[1:]
        dirname = home + "-my-project"
        result = clean_project_name(dirname)
        self.assertEqual(result, "my-project")

    def test_empty_string_returns_unknown(self):
        self.assertEqual(clean_project_name(""), "unknown")

    def test_leading_dash_stripped(self):
        result = clean_project_name("-some-project")
        self.assertEqual(result, "some-project")

    def test_plain_name_unchanged(self):
        result = clean_project_name("my-cool-project")
        self.assertEqual(result, "my-cool-project")


class TestNormalizeModelName(unittest.TestCase):
    """Tests for normalize_model_name()."""

    def test_opus(self):
        self.assertEqual(normalize_model_name("claude-opus-4-20250514"), "Opus")

    def test_sonnet(self):
        self.assertEqual(normalize_model_name("claude-sonnet-4-20250514"), "Sonnet")

    def test_haiku(self):
        self.assertEqual(normalize_model_name("claude-haiku-4-5-20251001"), "Haiku")

    def test_empty_string(self):
        self.assertEqual(normalize_model_name(""), "unknown")

    def test_none(self):
        self.assertEqual(normalize_model_name(None), "unknown")

    def test_unknown_returns_original(self):
        self.assertEqual(normalize_model_name("gpt-4"), "gpt-4")


class TestLengthBucket(unittest.TestCase):
    """Tests for length_bucket()."""

    def test_micro(self):
        self.assertEqual(length_bucket(5), "micro (<20)")

    def test_short(self):
        self.assertEqual(length_bucket(30), "short (20-50)")

    def test_medium(self):
        self.assertEqual(length_bucket(100), "medium (50-150)")

    def test_detailed(self):
        self.assertEqual(length_bucket(300), "detailed (150-500)")

    def test_comprehensive(self):
        self.assertEqual(length_bucket(1000), "comprehensive (500+)")

    def test_boundary_20(self):
        self.assertEqual(length_bucket(20), "short (20-50)")

    def test_boundary_50(self):
        self.assertEqual(length_bucket(50), "medium (50-150)")

    def test_boundary_150(self):
        self.assertEqual(length_bucket(150), "detailed (150-500)")

    def test_boundary_500(self):
        self.assertEqual(length_bucket(500), "comprehensive (500+)")

    def test_zero(self):
        self.assertEqual(length_bucket(0), "micro (<20)")


if __name__ == "__main__":
    unittest.main()

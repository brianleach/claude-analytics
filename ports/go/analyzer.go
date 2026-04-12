package main

import (
	"fmt"
	"strings"
)

// Recommendation represents a single recommendation entry.
type Recommendation struct {
	Title     string `json:"title"`
	Severity  string `json:"severity"`
	Body      string `json:"body"`
	Metric    string `json:"metric"`
	Example   string `json:"example"`
	RecSource string `json:"rec_source"`
}

// RecommendationResult holds all recommendations and their source.
type RecommendationResult struct {
	Recommendations []Recommendation `json:"recommendations"`
	Source          string           `json:"source"`
}

// findExamplePrompts finds real example prompts from a specific category.
func findExamplePrompts(prompts []Prompt, category string, maxCount int, maxLen int) []string {
	var matches []Prompt
	for _, p := range prompts {
		if p.Category == category && len(p.Text) > 15 {
			matches = append(matches, p)
		}
	}
	// Sort by full_length ascending
	for i := 0; i < len(matches)-1; i++ {
		for j := i + 1; j < len(matches); j++ {
			if matches[j].FullLength < matches[i].FullLength {
				matches[i], matches[j] = matches[j], matches[i]
			}
		}
	}
	var results []string
	for i, p := range matches {
		if i >= maxCount {
			break
		}
		text := p.Text
		if len(text) > maxLen {
			text = text[:maxLen]
		}
		results = append(results, text)
	}
	return results
}

// findShortPrompts finds real examples of short prompts.
func findShortPrompts(prompts []Prompt, maxChars int, maxCount int) []string {
	var short []Prompt
	for _, p := range prompts {
		if p.FullLength < maxChars && len(strings.TrimSpace(p.Text)) > 3 {
			short = append(short, p)
		}
	}
	if len(short) > maxCount {
		step := len(short) / maxCount
		var sampled []Prompt
		for i := 0; i < maxCount; i++ {
			sampled = append(sampled, short[i*step])
		}
		short = sampled
	}
	var results []string
	for _, p := range short {
		text := p.Text
		if len(text) > 80 {
			text = text[:80]
		}
		results = append(results, text)
	}
	return results
}

// GetHeuristicRecommendations generates recommendations using local heuristics.
func GetHeuristicRecommendations(
	analysis Analysis,
	summary Summary,
	workDays []WorkDay,
	prompts []Prompt,
	models []ModelBreakdown,
	subagents SubagentData,
	contextEfficiency ContextEfficiency,
	branches []BranchData,
	skills []SkillData,
	permissionModes map[string]int,
) []Recommendation {
	var recs []Recommendation
	total := analysis.TotalPrompts
	avgLen := analysis.AvgLength
	_ = total

	if prompts == nil {
		prompts = []Prompt{}
	}
	if permissionModes == nil {
		permissionModes = map[string]int{}
	}

	// Build lookup maps
	catMap := map[string]CategoryStat{}
	for _, c := range analysis.Categories {
		catMap[c.Cat] = c
	}
	lbMap := map[string]LengthBucketStat{}
	for _, l := range analysis.LengthBuckets {
		lbMap[l.Bucket] = l
	}

	microPct := lbMap["micro (<20)"].Pct
	shortPct := lbMap["short (20-50)"].Pct
	debugPct := catMap["debugging"].Pct
	testPct := catMap["testing"].Pct
	refPct := catMap["refactoring"].Pct
	qPct := catMap["question"].Pct
	buildPct := catMap["building"].Pct
	confirmPct := catMap["confirmation"].Pct
	_ = catMap["editing"].Pct

	// 1. Prompt specificity
	if microPct+shortPct > 25 {
		shortExamples := findShortPrompts(prompts, 50, 5)
		exampleBlock := ""
		if len(shortExamples) > 0 {
			exampleBlock = "Your short prompts include:\n"
			limit := 3
			if len(shortExamples) < limit {
				limit = len(shortExamples)
			}
			for _, ex := range shortExamples[:limit] {
				exampleBlock += fmt.Sprintf("  > \"%s\"\n", ex)
			}
			exampleBlock += "\nTry instead:\n"
			exampleBlock += "\"Fix the login form in src/auth/LoginForm.tsx - it shows a blank screen after submitting valid credentials. The handleSubmit callback should redirect to /dashboard but router.push isn't firing.\""
		}

		var bodyText string
		var severity string
		if avgLen > 200 {
			bodyText = fmt.Sprintf(
				"%.0f%% of your prompts are under 50 characters (though your avg is %d chars - a bimodal pattern). "+
					"Those short prompts are often confirmations or follow-ups that force extra round-trips. "+
					"Try batching context into fewer, richer prompts.",
				microPct+shortPct, avgLen,
			)
			severity = "medium"
		} else {
			bodyText = fmt.Sprintf(
				"%.0f%% of your prompts are under 50 characters. "+
					"Short prompts force Claude to guess, burning tokens on clarification. "+
					"Include: file path, expected vs actual behavior, and constraints. "+
					"A specific 100-char prompt saves 5 rounds of back-and-forth.",
				microPct+shortPct,
			)
			severity = "high"
		}

		example := exampleBlock
		if example == "" {
			example = "Instead of \"fix the bug\", try:\n\"Fix the login form in src/auth/LoginForm.tsx - blank screen after submit. handleSubmit should redirect to /dashboard.\""
		}

		recs = append(recs, Recommendation{
			Title:    "Front-load context in your prompts",
			Severity: severity,
			Body:     bodyText,
			Metric:   fmt.Sprintf("your avg: %d chars | %.0f%% under 50 chars", avgLen, microPct+shortPct),
			Example:  example,
		})
	}

	// 2. High confirmation ratio
	if confirmPct > 15 {
		confirmExamples := findExamplePrompts(prompts, "confirmation", 3, 150)
		exampleBlock := ""
		if len(confirmExamples) > 0 {
			exampleBlock = "Your confirmation prompts include:\n"
			limit := 3
			if len(confirmExamples) < limit {
				limit = len(confirmExamples)
			}
			for _, ex := range confirmExamples[:limit] {
				exampleBlock += fmt.Sprintf("  > \"%s\"\n", ex)
			}
			exampleBlock += "\nEliminate these by adding to CLAUDE.md:\n"
			exampleBlock += "- Auto-fix lint errors without asking\n"
			exampleBlock += "- Run tests after every code change\n"
			exampleBlock += "- Commit with descriptive messages, don't ask for approval"
		}
		if exampleBlock == "" {
			exampleBlock = "Add to CLAUDE.md:\n- Auto-fix lint errors without asking\n- Run tests after every code change\n- Commit with descriptive messages, don't ask for approval"
		}

		recs = append(recs, Recommendation{
			Title:    "Reduce confirmation ping-pong",
			Severity: "medium",
			Body: fmt.Sprintf(
				"%.0f%% of your prompts are confirmations (yes, ok, go ahead, etc). "+
					"This suggests Claude is asking for permission too often. Set up a "+
					"CLAUDE.md with your conventions so Claude can act autonomously, and "+
					"use permission mode flags to reduce approval prompts.",
				confirmPct,
			),
			Metric:  fmt.Sprintf("%.0f%% confirmations | target: <10%%", confirmPct),
			Example: exampleBlock,
		})
	}

	// 3. Debug ratio
	if debugPct > 12 {
		debugExamples := findExamplePrompts(prompts, "debugging", 3, 150)
		exampleBlock := ""
		if len(debugExamples) > 0 {
			exampleBlock = "Your debugging prompts:\n"
			limit := 2
			if len(debugExamples) < limit {
				limit = len(debugExamples)
			}
			for _, ex := range debugExamples[:limit] {
				exampleBlock += fmt.Sprintf("  > \"%s\"\n", ex)
			}
			exampleBlock += "\nLevel up by including:\n"
			exampleBlock += "- The full error message and stack trace\n"
			exampleBlock += "- What you expected vs what happened\n"
			exampleBlock += "- Steps to reproduce"
		}
		if exampleBlock == "" {
			exampleBlock = "\"Fix the crash in PaymentService.processOrder() - here's the stack trace: [paste]. It fails when the cart has items with quantity > 99.\""
		}

		sev := "medium"
		if debugPct > 20 {
			sev = "high"
		}
		recs = append(recs, Recommendation{
			Title:    "Reduce debugging cycles",
			Severity: sev,
			Body: fmt.Sprintf(
				"%.0f%% of your prompts are debugging. Reduce this by: "+
					"1) pasting full error messages + stack traces upfront, "+
					"2) asking Claude to add error handling proactively when building, "+
					"3) requesting defensive coding patterns like input validation.",
				debugPct,
			),
			Metric:  fmt.Sprintf("%.0f%% debugging | target: <10%%", debugPct),
			Example: exampleBlock,
		})
	}

	// 4. Testing
	if testPct < 5 {
		recs = append(recs, Recommendation{
			Title:    "Ask for tests alongside features",
			Severity: "medium",
			Body: fmt.Sprintf(
				"Only %.0f%% of prompts mention testing. "+
					"Bundling test requests with feature work catches regressions early "+
					"and forces Claude to think about edge cases during implementation. "+
					"This is one of Claude's strongest capabilities - use it.",
				testPct,
			),
			Metric: fmt.Sprintf("%.0f%% testing | recommended: 10-15%%", testPct),
			Example: "\"Implement the user search endpoint and write tests covering: " +
				"empty query, special characters, pagination boundaries, and a " +
				"user with no matching results.\"",
		})
	}

	// 5. Questions
	if qPct < 8 {
		recs = append(recs, Recommendation{
			Title:    "Use Claude as a thinking partner first",
			Severity: "medium",
			Body: fmt.Sprintf(
				"Only %.0f%% of your prompts are questions. "+
					"Before diving into implementation, spend 30 seconds asking Claude "+
					"to explain tradeoffs, review your approach, or suggest architecture. "+
					"A quick question prevents expensive wrong turns.",
				qPct,
			),
			Metric: fmt.Sprintf("%.0f%% questions | consider: 10-15%%", qPct),
			Example: "\"Before I implement caching, walk me through the tradeoffs between " +
				"Redis and in-memory for our case. We have ~1000 req/min and data " +
				"changes every 5 minutes. What would you recommend?\"",
		})
	}

	// 6. Refactoring
	if refPct < 3 {
		recs = append(recs, Recommendation{
			Title:    "Schedule refactoring passes",
			Severity: "low",
			Body: fmt.Sprintf(
				"Only %.0f%% of prompts involve refactoring. "+
					"After features ship, ask Claude to clean up. It excels at "+
					"mechanical refactoring - extracting shared utils, simplifying "+
					"complex functions, improving naming, reducing duplication.",
				refPct,
			),
			Metric: fmt.Sprintf("%.0f%% refactoring | healthy: 5-10%%", refPct),
			Example: "\"Review src/api/ for duplicated logic across endpoints. " +
				"Extract shared patterns into middleware or utility functions. " +
				"Don't change behavior, just clean up the structure.\"",
		})
	}

	// 7. Batching (high messages per session)
	avgMsgs := float64(summary.TotalUserMsgs) / float64(maxInt(summary.TotalSessions, 1))
	if avgMsgs > 100 {
		recs = append(recs, Recommendation{
			Title:    "Batch related changes into single prompts",
			Severity: "medium",
			Body: fmt.Sprintf(
				"You average %.0f messages per session. "+
					"Try combining related changes: instead of 5 separate prompts "+
					"for 5 files, list all changes in one. Claude handles multi-file "+
					"changes well and produces more coherent diffs.",
				avgMsgs,
			),
			Metric: fmt.Sprintf("%.0f msgs/session avg", avgMsgs),
			Example: "\"Rename userService to authService across the codebase: " +
				"1) rename the file, 2) update all imports, " +
				"3) update tests, 4) update config references.\"",
		})
	}

	// 8. CLAUDE.md
	if confirmPct > 10 || microPct > 15 {
		recs = append(recs, Recommendation{
			Title:    "Use CLAUDE.md for persistent context",
			Severity: "low",
			Body: "Put project conventions, file structure, and recurring instructions " +
				"in a CLAUDE.md file in your project root. Claude reads it at session " +
				"start, so you never have to repeat setup instructions. This single " +
				"file can eliminate dozens of wasted prompts per session.",
			Metric: fmt.Sprintf("%d sessions could each save setup prompts", summary.TotalSessions),
			Example: "# CLAUDE.md\n" +
				"- React Native app using Expo + TypeScript strict\n" +
				"- Run tests: npx jest --watchAll=false\n" +
				"- Always use functional components with hooks\n" +
				"- API config in src/config/api.ts\n" +
				"- Don't ask before running tests or fixing lint",
		})
	}

	// 9. Model selection
	if len(models) > 0 {
		var opusModel *ModelBreakdown
		for i := range models {
			if models[i].Display == "Opus" {
				opusModel = &models[i]
				break
			}
		}
		totalCost := summary.EstimatedCost

		if opusModel != nil && totalCost > 0 {
			opusPct := int(opusModel.EstimatedCost / totalCost * 100)
			if opusPct > 70 {
				sev := "medium"
				if opusPct > 85 {
					sev = "high"
				}
				recs = append(recs, Recommendation{
					Title:    "Use lighter models for routine tasks",
					Severity: sev,
					Body: fmt.Sprintf(
						"Opus accounts for %d%% of your estimated API cost. "+
							"For routine tasks like file searches, simple edits, code formatting, "+
							"and grep operations, Sonnet or Haiku are 5-20x cheaper and just as "+
							"effective. Reserve Opus for complex reasoning and architecture.",
						opusPct,
					),
					Metric: fmt.Sprintf("Opus: %d%% of spend | Haiku is 19x cheaper per token", opusPct),
					Example: "Use Claude Code's model selection:\n" +
						"- /model haiku  -> quick lookups, file searches, simple fixes\n" +
						"- /model sonnet -> standard coding, refactoring, tests\n" +
						"- /model opus   -> complex architecture, debugging hard issues",
				})
			}
		}
	}

	// 10. Subagent usage
	saCount := subagents.TotalCount
	saTypes := subagents.TypeCounts
	exploreCount := saTypes["Explore"]
	gpCount := saTypes["general-purpose"]

	if saCount > 0 {
		if gpCount > exploreCount && gpCount > 20 {
			recs = append(recs, Recommendation{
				Title:    "Prefer Explore agents over general-purpose",
				Severity: "medium",
				Body: fmt.Sprintf(
					"You spawned %d general-purpose agents vs %d Explore agents. "+
						"Explore agents use Haiku (much cheaper) and are optimized for "+
						"code search, file discovery, and quick lookups. Use general-purpose "+
						"only when the subagent needs to write code or make complex decisions.",
					gpCount, exploreCount,
				),
				Metric: fmt.Sprintf("%d general-purpose | %d Explore agents", gpCount, exploreCount),
				Example: "Claude automatically picks agent types, but you can influence it:\n" +
					"- 'find all files that import UserService' -> Explore agent\n" +
					"- 'search for how auth is implemented' -> Explore agent\n" +
					"- 'refactor the auth module' -> general-purpose agent",
			})
		} else if saCount < 10 && summary.TotalSessions > 20 {
			recs = append(recs, Recommendation{
				Title:    "Let Claude use subagents for parallel work",
				Severity: "low",
				Body: fmt.Sprintf(
					"You've only spawned %d subagents across %d sessions. "+
						"Subagents let Claude search code, explore files, and run tasks in "+
						"parallel. For complex tasks, explicitly ask Claude to 'search in parallel' "+
						"or 'explore multiple approaches' to unlock this.",
					saCount, summary.TotalSessions,
				),
				Metric: fmt.Sprintf("%d subagents across %d sessions", saCount, summary.TotalSessions),
				Example: "\"Find all API endpoints that don't have authentication middleware " +
					"and search for any tests that cover unauthenticated access - do both " +
					"searches in parallel.\"",
			})
		}
	}

	// 11. Compaction events
	compactionCount := subagents.CompactionCount
	if compactionCount > 3 {
		sev := "medium"
		if compactionCount > 10 {
			sev = "high"
		}
		recs = append(recs, Recommendation{
			Title:    "Start fresh sessions more often",
			Severity: sev,
			Body: fmt.Sprintf(
				"Your sessions triggered %d context compactions - "+
					"meaning Claude's context window filled up and had to be summarized. "+
					"After compaction, Claude loses nuance from earlier in the conversation. "+
					"Start new sessions when switching tasks or after major milestones.",
				compactionCount,
			),
			Metric: fmt.Sprintf("%d compactions | each loses context detail", compactionCount),
			Example: "Good session boundaries:\n" +
				"- After completing a feature -> new session for the next one\n" +
				"- After a successful deploy -> new session for bug fixes\n" +
				"- When switching projects -> always start fresh",
		})
	}

	// 12. Context efficiency
	toolPct := contextEfficiency.ToolPct
	if toolPct > 85 {
		recs = append(recs, Recommendation{
			Title:    "Reduce context window bloat from tool output",
			Severity: "medium",
			Body: fmt.Sprintf(
				"%.0f%% of Claude's output goes to tool results (file reads, "+
					"command output, search results). This fills the context window fast. "+
					"Use targeted file reads (specific line ranges), limit grep results, "+
					"and ask Claude to search for specific patterns rather than reading entire files.",
				toolPct,
			),
			Metric:  fmt.Sprintf("%.0f%% tool output | %.0f%% conversation", toolPct, contextEfficiency.ConversationPct),
			Example: "Instead of: 'read the entire auth module'\nTry: 'read the handleLogin function in src/auth/login.ts (around line 45-80)'\n\nInstead of: 'search for all uses of UserContext'\nTry: 'find where UserContext.Provider is rendered (should be in App.tsx)'",
		})
	}

	// 13. Thinking blocks
	thinking := contextEfficiency.ThinkingBlocks
	if thinking > 0 && total > 0 {
		thinkingPerSession := float64(thinking) / float64(maxInt(summary.TotalSessions, 1))
		if thinkingPerSession > 15 {
			recs = append(recs, Recommendation{
				Title:    "Extended thinking is being used heavily",
				Severity: "low",
				Body: fmt.Sprintf(
					"Claude used extended thinking %d times across your sessions "+
						"(~%.0f/session). This is great for complex problems "+
						"but uses more tokens. For simple tasks, you can nudge Claude to act "+
						"directly: 'just do it, no need to overthink this.'",
					thinking, thinkingPerSession,
				),
				Metric: fmt.Sprintf("%d thinking blocks | %.0f/session", thinking, thinkingPerSession),
				Example: "Thinking is valuable for:\n" +
					"- Debugging complex race conditions\n" +
					"- Designing system architecture\n" +
					"- Multi-file refactoring plans\n\n" +
					"Skip it for: simple renames, formatting, straightforward edits",
			})
		}
	}

	// 14. MCP/skill usage
	if len(skills) > 0 {
		skillCount := len(skills)
		if skillCount < 3 {
			recs = append(recs, Recommendation{
				Title:    "Explore more MCP integrations",
				Severity: "low",
				Body: fmt.Sprintf(
					"You're using %d MCP tool(s). Claude Code supports "+
						"integrations with Linear, GitHub, Sentry, Figma, Slack, and many more. "+
						"MCP tools let Claude take actions directly in your tools - creating "+
						"tickets, fetching error reports, reading designs - without leaving the terminal.",
					skillCount,
				),
				Metric: fmt.Sprintf("%d MCP integrations active", skillCount),
				Example: "Popular MCP integrations:\n" +
					"- Linear: create/update tickets from code context\n" +
					"- Sentry: fetch error details for debugging\n" +
					"- Figma: read designs for implementation\n" +
					"- GitHub: manage PRs and issues",
			})
		}
	}

	// === BORIS CHERNY BEST PRACTICES ===

	// 15. Verification feedback loop
	if buildPct > 10 && testPct < 5 {
		recs = append(recs, Recommendation{
			Title:    "Give Claude a way to verify its work",
			Severity: "high",
			Body: fmt.Sprintf(
				"You're building %.0f%% of the time but only testing %.0f%%. "+
					"The single most impactful Claude Code habit: give it a feedback loop. "+
					"When Claude can run tests after every change, output quality jumps 2-3x. "+
					"Add test commands to CLAUDE.md so Claude runs them automatically.",
				buildPct, testPct,
			),
			Metric: fmt.Sprintf("%.0f%% building | %.0f%% testing | recommended: test every change", buildPct, testPct),
			Example: "Add to CLAUDE.md:\n" +
				"- After ANY code change, run: npm test -- --related\n" +
				"- After UI changes, run: npx playwright test\n" +
				"- Before committing, run: npm run lint && npm run typecheck\n\n" +
				"Or use a PostToolUse hook in .claude/settings.json to auto-format/test.",
		})
	}

	// 16. Permission mode
	defaultPM := permissionModes["default"]
	totalPM := 0
	for _, v := range permissionModes {
		totalPM += v
	}
	if totalPM == 0 {
		totalPM = 1
	}
	if float64(defaultPM)/float64(totalPM) > 0.5 {
		pct := float64(defaultPM) / float64(totalPM) * 100
		recs = append(recs, Recommendation{
			Title:    "Use /permissions instead of clicking allow",
			Severity: "medium",
			Body: fmt.Sprintf(
				"%.0f%% of your messages are in default permission mode. "+
					"You're likely clicking 'allow' repeatedly for safe commands. Use /permissions "+
					"to pre-approve safe commands (git, npm test, lint) and check them into "+
					".claude/settings.json to share with your team.",
				pct,
			),
			Metric: fmt.Sprintf("%.0f%% default mode | consider: acceptEdits or custom permissions", pct),
			Example: "In .claude/settings.json:\n" +
				"{\"permissions\": {\"allow\": [\n" +
				"  \"Bash(npm test*)\", \"Bash(npm run lint*)\",\n" +
				"  \"Bash(git status*)\", \"Bash(git diff*)\",\n" +
				"  \"Read\", \"Glob\", \"Grep\"\n" +
				"]}}\n\n" +
				"Safer than --dangerously-skip-permissions, shared via git.",
		})
	}

	// 17. Hooks for formatting
	formatCount := 0
	for _, p := range prompts {
		t := strings.ToLower(p.Text)
		if strings.Contains(t, "lint") || strings.Contains(t, "format") ||
			strings.Contains(t, "prettier") || strings.Contains(t, "eslint") ||
			strings.Contains(t, "formatting") {
			formatCount++
		}
	}
	if formatCount > 5 {
		recs = append(recs, Recommendation{
			Title:    "Use a PostToolUse hook for auto-formatting",
			Severity: "medium",
			Body: fmt.Sprintf(
				"You have %d prompts about formatting/linting. "+
					"Set up a PostToolUse hook to auto-format code after Claude edits it. "+
					"Claude generates well-formatted code 90%% of the time - the hook handles "+
					"the last 10%% so you never waste prompts on formatting issues.",
				formatCount,
			),
			Metric:  fmt.Sprintf("%d format-related prompts | target: 0 (automated)", formatCount),
			Example: "In .claude/settings.json:\n{\"hooks\": {\"PostToolUse\": [{\n  \"matcher\": \"Edit|Write\",\n  \"command\": \"npx prettier --write $FILE_PATH\"\n}]}}\n\nNow every file Claude touches is auto-formatted.",
		})
	}

	// 18. Long sessions
	longSessionCount := 0
	for _, wd := range workDays {
		if wd.ActiveHrs > 4 {
			longSessionCount++
		}
	}
	if longSessionCount > 3 {
		recs = append(recs, Recommendation{
			Title:    "Use background agents for long tasks",
			Severity: "low",
			Body: fmt.Sprintf(
				"You have %d sessions over 4 hours. For long-running "+
					"tasks, ask Claude to verify its work with a background agent when done, "+
					"or use an AgentStop hook to run validation automatically. This catches "+
					"drift and regressions in marathon sessions.",
				longSessionCount,
			),
			Metric: fmt.Sprintf("%d sessions > 4h active time", longSessionCount),
			Example: "At the end of a long feature task, say:\n" +
				"\"Before you finish, run the full test suite and verify all TypeScript " +
				"types still compile. If anything fails, fix it.\"\n\n" +
				"Or add a Stop hook that runs tests when a session ends.",
		})
	}

	return recs
}

// GenerateRecommendations generates recommendations (heuristic only in Go port).
func GenerateRecommendations(data *ParseResult) RecommendationResult {
	recs := GetHeuristicRecommendations(
		data.Analysis,
		data.Dashboard.Summary,
		data.WorkDays,
		data.Prompts,
		data.Models,
		data.Subagents,
		data.ContextEfficiency,
		data.Branches,
		data.Skills,
		data.PermissionModes,
	)

	for i := range recs {
		recs[i].RecSource = "heuristic"
	}

	if recs == nil {
		recs = []Recommendation{}
	}

	return RecommendationResult{
		Recommendations: recs,
		Source:          "heuristic",
	}
}

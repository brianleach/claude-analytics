package main

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Canonical source: shared/heuristic_rules.json
// This file is copied here because go:embed cannot reference parent directories.
//
//go:embed heuristic_rules.json
var heuristicRulesJSON string

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

// heuristicRule mirrors the JSON schema in shared/heuristic_rules.json.
type heuristicRule struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	Section   string `json:"section"`
	Condition struct {
		Type           string             `json:"type"`
		Metric         string             `json:"metric,omitempty"`
		Metrics        []string           `json:"metrics,omitempty"`
		ComputedMetric string             `json:"computed_metric,omitempty"`
		Operator       string             `json:"operator,omitempty"`
		Threshold      float64            `json:"threshold,omitempty"`
		Conditions     []ruleConditionJSON `json:"conditions,omitempty"`
		Excludes       string             `json:"excludes,omitempty"`
	} `json:"condition"`
	Severity         string `json:"severity"`
	SeverityOverride *struct {
		Condition ruleConditionJSON `json:"condition"`
		Severity  string            `json:"severity"`
	} `json:"severity_override,omitempty"`
	BodyTemplate         string            `json:"body_template,omitempty"`
	BodyVariants         map[string]string `json:"body_variants,omitempty"`
	BodyVariantCondition *struct {
		ruleConditionJSON
		Variant string `json:"variant"`
	} `json:"body_variant_condition,omitempty"`
	MetricTemplate    string `json:"metric_template"`
	ExampleType       string `json:"example_type,omitempty"`
	ExampleCategory   string `json:"example_category,omitempty"`
	ExampleMaxCount   int    `json:"example_max_count,omitempty"`
	ExamplePreamble   string `json:"example_preamble,omitempty"`
	ExampleSuggestion string `json:"example_suggestion,omitempty"`
	FallbackExample   string `json:"fallback_example"`
}

type ruleConditionJSON struct {
	Metric          string  `json:"metric,omitempty"`
	Operator        string  `json:"operator,omitempty"`
	Threshold       float64 `json:"threshold,omitempty"`
	ThresholdMetric string  `json:"threshold_metric,omitempty"`
}

var (
	parsedRules     []heuristicRule
	parsedRulesOnce sync.Once
	templateRE      = regexp.MustCompile(`\{\{(\w+)(?::([^}]+))?\}\}`)
)

func loadHeuristicRules() []heuristicRule {
	parsedRulesOnce.Do(func() {
		if err := json.Unmarshal([]byte(heuristicRulesJSON), &parsedRules); err != nil {
			parsedRules = nil
		}
	})
	return parsedRules
}

func renderTemplate(tmpl string, vals map[string]float64) string {
	return templateRE.ReplaceAllStringFunc(tmpl, func(match string) string {
		parts := templateRE.FindStringSubmatch(match)
		key := parts[1]
		format := parts[2]
		val, ok := vals[key]
		if !ok {
			return ""
		}
		if format != "" {
			// Handle :.0f style formats
			if strings.HasSuffix(format, "f") && strings.HasPrefix(format, ".") {
				prec := 0
				if p, err := strconv.Atoi(format[1 : len(format)-1]); err == nil {
					prec = p
				}
				return strconv.FormatFloat(val, 'f', prec, 64)
			}
		}
		// Integer-like values
		if val == math.Trunc(val) {
			return strconv.Itoa(int(val))
		}
		return strconv.FormatFloat(val, 'f', -1, 64)
	})
}

func checkRuleCondition(cond ruleConditionJSON, vals map[string]float64) bool {
	metricVal := vals[cond.Metric]
	threshold := cond.Threshold
	if cond.ThresholdMetric != "" {
		threshold = vals[cond.ThresholdMetric]
	}
	switch cond.Operator {
	case ">":
		return metricVal > threshold
	case "<":
		return metricVal < threshold
	case ">=":
		return metricVal >= threshold
	case "<=":
		return metricVal <= threshold
	}
	return false
}

// GetHeuristicRecommendations generates recommendations using shared heuristic rules.
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
	rules := loadHeuristicRules()
	var recs []Recommendation

	if prompts == nil {
		prompts = []Prompt{}
	}
	if permissionModes == nil {
		permissionModes = map[string]int{}
	}

	total := analysis.TotalPrompts
	avgLen := analysis.AvgLength

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

	avgMsgs := float64(summary.TotalUserMsgs) / float64(maxInt(summary.TotalSessions, 1))
	totalSessions := float64(summary.TotalSessions)

	opusPct := 0.0
	if len(models) > 0 {
		totalCost := summary.EstimatedCost
		for _, m := range models {
			if m.Display == "Opus" && totalCost > 0 {
				opusPct = math.Round(m.EstimatedCost / totalCost * 100)
			}
		}
	}

	saCount := float64(subagents.TotalCount)
	exploreCount := float64(subagents.TypeCounts["Explore"])
	gpCount := float64(subagents.TypeCounts["general-purpose"])
	compactionCount := float64(subagents.CompactionCount)

	toolPct := contextEfficiency.ToolPct
	conversationPct := contextEfficiency.ConversationPct
	thinking := float64(contextEfficiency.ThinkingBlocks)
	thinkingPerSession := thinking / math.Max(totalSessions, 1)

	skillCount := float64(len(skills))

	defaultPM := float64(permissionModes["default"])
	totalPM := 0.0
	for _, v := range permissionModes {
		totalPM += float64(v)
	}
	if totalPM == 0 {
		totalPM = 1
	}
	defaultPMRatio := defaultPM / totalPM
	defaultPMPct := defaultPMRatio * 100

	formatCount := 0.0
	for _, p := range prompts {
		t := strings.ToLower(p.Text)
		if strings.Contains(t, "lint") || strings.Contains(t, "format") ||
			strings.Contains(t, "prettier") || strings.Contains(t, "eslint") ||
			strings.Contains(t, "formatting") {
			formatCount++
		}
	}

	longSessionCount := 0.0
	for _, wd := range workDays {
		if wd.ActiveHrs > 4 {
			longSessionCount++
		}
	}

	vals := map[string]float64{
		"total": float64(total), "avg_len": float64(avgLen),
		"micro_pct": microPct, "short_pct": shortPct,
		"micro_short_pct": microPct + shortPct,
		"debug_pct": debugPct, "test_pct": testPct,
		"ref_pct": refPct, "q_pct": qPct,
		"build_pct": buildPct, "confirm_pct": confirmPct,
		"avg_msgs": avgMsgs, "total_sessions": totalSessions,
		"opus_pct": opusPct,
		"sa_count": saCount, "explore_count": exploreCount, "gp_count": gpCount,
		"compaction_count": compactionCount,
		"tool_pct": toolPct, "conversation_pct": conversationPct,
		"thinking": thinking, "thinking_per_session": thinkingPerSession,
		"skill_count": skillCount,
		"default_pm_ratio": defaultPMRatio, "default_pm_pct": defaultPMPct,
		"format_prompt_count": formatCount,
		"long_session_count": longSessionCount,
	}

	triggeredIDs := map[string]bool{}

	for _, rule := range rules {
		cond := rule.Condition

		switch cond.Type {
		case "simple":
			if !checkRuleCondition(ruleConditionJSON{
				Metric: cond.Metric, Operator: cond.Operator, Threshold: cond.Threshold,
			}, vals) {
				continue
			}
		case "sum_gt":
			sum := 0.0
			for _, m := range cond.Metrics {
				sum += vals[m]
			}
			if sum <= cond.Threshold {
				continue
			}
		case "or":
			any := false
			for _, c := range cond.Conditions {
				if checkRuleCondition(c, vals) {
					any = true
					break
				}
			}
			if !any {
				continue
			}
		case "compound_and":
			all := true
			for _, c := range cond.Conditions {
				if !checkRuleCondition(c, vals) {
					all = false
					break
				}
			}
			if !all {
				continue
			}
			if cond.Excludes != "" && triggeredIDs[cond.Excludes] {
				continue
			}
		case "computed":
			if !checkRuleCondition(ruleConditionJSON{
				Metric: cond.ComputedMetric, Operator: cond.Operator, Threshold: cond.Threshold,
			}, vals) {
				continue
			}
		default:
			continue
		}

		triggeredIDs[rule.ID] = true

		// Severity
		severity := rule.Severity
		if rule.SeverityOverride != nil {
			if checkRuleCondition(rule.SeverityOverride.Condition, vals) {
				severity = rule.SeverityOverride.Severity
			}
		}

		// Body
		var body string
		if len(rule.BodyVariants) > 0 {
			variant := "default"
			if rule.BodyVariantCondition != nil {
				if checkRuleCondition(rule.BodyVariantCondition.ruleConditionJSON, vals) {
					variant = rule.BodyVariantCondition.Variant
				}
			}
			body = renderTemplate(rule.BodyVariants[variant], vals)
		} else {
			body = renderTemplate(rule.BodyTemplate, vals)
		}

		metric := renderTemplate(rule.MetricTemplate, vals)

		// Example
		example := ""
		switch rule.ExampleType {
		case "short_prompts":
			shortExamples := findShortPrompts(prompts, 50, 5)
			if len(shortExamples) > 0 {
				example = rule.ExamplePreamble + "\n"
				limit := 3
				if len(shortExamples) < limit {
					limit = len(shortExamples)
				}
				for _, ex := range shortExamples[:limit] {
					example += fmt.Sprintf("  > \"%s\"\n", ex)
				}
				example += "\n" + rule.ExampleSuggestion
			}
		case "category_prompts":
			maxCount := rule.ExampleMaxCount
			if maxCount == 0 {
				maxCount = 3
			}
			catExamples := findExamplePrompts(prompts, rule.ExampleCategory, maxCount, 150)
			if len(catExamples) > 0 {
				example = rule.ExamplePreamble + "\n"
				limit := maxCount
				if len(catExamples) < limit {
					limit = len(catExamples)
				}
				for _, ex := range catExamples[:limit] {
					example += fmt.Sprintf("  > \"%s\"\n", ex)
				}
				example += "\n" + rule.ExampleSuggestion
			}
		}

		if example == "" {
			example = rule.FallbackExample
		}

		recs = append(recs, Recommendation{
			Title:    rule.Title,
			Severity: severity,
			Body:     body,
			Metric:   metric,
			Example:  example,
		})
	}

	return recs
}

// getAiRecommendations calls the Anthropic API for AI-powered recommendations.
func getAiRecommendations(
	analysis Analysis,
	summary Summary,
	promptsSample []Prompt,
	workDays []WorkDay,
	models []ModelBreakdown,
	subagents SubagentData,
	contextEfficiency ContextEfficiency,
	branches []BranchData,
	skills []SkillData,
	permissionModes map[string]int,
) ([]Recommendation, error) {
	apiKey := os.Getenv("ANTHROPIC_API_KEY")
	if apiKey == "" {
		return nil, fmt.Errorf("ANTHROPIC_API_KEY not set")
	}

	// === Build rich context ===
	var catParts []string
	limit := 8
	if len(analysis.Categories) < limit {
		limit = len(analysis.Categories)
	}
	for _, c := range analysis.Categories[:limit] {
		catParts = append(catParts, fmt.Sprintf("%s: %.0f%%", c.Cat, c.Pct))
	}
	catSummary := strings.Join(catParts, ", ")

	var lenParts []string
	for _, l := range analysis.LengthBuckets {
		lenParts = append(lenParts, fmt.Sprintf("%s: %.0f%%", l.Bucket, l.Pct))
	}
	lenSummary := strings.Join(lenParts, ", ")

	// Sample prompts by category
	sampleByCat := map[string][]Prompt{}
	for _, p := range promptsSample {
		cat := p.Category
		if len(sampleByCat[cat]) < 5 {
			sampleByCat[cat] = append(sampleByCat[cat], p)
		}
	}
	var sampleText string
	for cat, samples := range sampleByCat {
		sampleText += fmt.Sprintf("\n### %s (%d samples)\n", cat, len(samples))
		for _, s := range samples {
			text := s.Text
			if len(text) > 300 {
				text = text[:300]
			}
			sampleText += fmt.Sprintf("  [%s] (%dch) \"%s\"\n", s.Project, s.FullLength, text)
		}
	}

	// Work pattern
	workSummary := "No work pattern data"
	if len(workDays) > 0 {
		totalActive := 0.0
		totalPrompts := 0
		for _, d := range workDays {
			totalActive += d.ActiveHrs
			totalPrompts += d.Prompts
		}
		avgDaily := totalActive / float64(len(workDays))
		avgPrompts := float64(totalPrompts) / float64(len(workDays))
		workSummary = fmt.Sprintf(
			"Active days: %d, avg active hours/day: %.1fh, avg prompts/day: %.0f, total active hours: %.1fh",
			len(workDays), avgDaily, avgPrompts, totalActive,
		)
	}

	// Model usage
	modelText := "No model data"
	if len(models) > 0 {
		var mParts []string
		for _, m := range models {
			if m.Msgs > 0 {
				mParts = append(mParts, fmt.Sprintf("  %s: %d msgs, $%.2f estimated cost", m.Display, m.Msgs, m.EstimatedCost))
			}
		}
		if len(mParts) > 0 {
			modelText = strings.Join(mParts, "\n")
		}
	}

	// Subagent usage
	saText := "No subagent data"
	if subagents.TotalCount > 0 {
		tcJSON, _ := json.Marshal(subagents.TypeCounts)
		saText = fmt.Sprintf(
			"Total: %d, Compactions: %d\n  Types: %s\n  Subagent cost: $%.2f",
			subagents.TotalCount, subagents.CompactionCount, string(tcJSON), subagents.EstimatedCost,
		)
	}

	// Context efficiency
	ceText := "No context data"
	if contextEfficiency.ToolOutputTokens > 0 || contextEfficiency.ConversationTokens > 0 {
		ceText = fmt.Sprintf(
			"Tool output: %.0f%%, Conversation: %.0f%%, Thinking blocks: %d, Subagent output share: %.0f%%",
			contextEfficiency.ToolPct, contextEfficiency.ConversationPct,
			contextEfficiency.ThinkingBlocks, contextEfficiency.SubagentPct,
		)
	}

	// Branch summary
	branchText := "No branch data"
	if len(branches) > 0 {
		var bParts []string
		bLimit := 10
		if len(branches) < bLimit {
			bLimit = len(branches)
		}
		for _, b := range branches[:bLimit] {
			bParts = append(bParts, fmt.Sprintf("  %s: %d msgs, %d sessions", b.Branch, b.Msgs, b.Sessions))
		}
		branchText = strings.Join(bParts, "\n")
	}

	// Permission modes
	pmText := "No permission data"
	if len(permissionModes) > 0 {
		totalPM := 0
		for _, v := range permissionModes {
			totalPM += v
		}
		var pmParts []string
		for k, v := range permissionModes {
			pmParts = append(pmParts, fmt.Sprintf("%s: %d (%d%%)", k, v, v*100/maxInt(totalPM, 1)))
		}
		pmText = strings.Join(pmParts, ", ")
	}

	// Project quality JSON
	pqLimit := 8
	if len(analysis.ProjectQuality) < pqLimit {
		pqLimit = len(analysis.ProjectQuality)
	}
	pqJSON, _ := json.MarshalIndent(analysis.ProjectQuality[:pqLimit], "", "  ")

	prompt := fmt.Sprintf(`You are a senior Claude Code power user coaching another developer. You know Claude Code deeply — its features, hidden capabilities, and common anti-patterns. Your job: look at this developer's ACTUAL usage data and tell them exactly what to change.

Rules for your recommendations:
- NEVER be generic. Every sentence must reference a specific number, project name, or prompt from their data.
- Quote their ACTUAL prompts in examples (from the samples below) and rewrite them better.
- Know Claude Code features: CLAUDE.md files, /model switching (opus/sonnet/haiku), subagent types (Explore for search, general-purpose for code changes), permission modes, hooks, extended thinking, MCP integrations, /compact command, worktrees.
- Think in terms of ROI: what change saves them the most time or money per effort?
- Be blunt. If they're wasting money, say so with the dollar amount. If their prompts suck, show them why.

## Their Data

### Overview
- %d prompts across %d sessions, %d projects
- Date range: %s to %s
- Average prompt length: %d chars
- Estimated API cost: $%.2f
- %s

### Prompt Categories (what they ask Claude to do)
%s

### Prompt Length Distribution
%s

### Model Usage & Cost
%s

### Subagent Usage
%s

### Context Window Efficiency
%s

### Git Branch Activity
%s

### Permission Modes
%s

### Project Quality Scores (per-project prompt patterns)
%s

### REAL Prompts From This User (use these in before/after examples)
%s

## Expert Best Practices (from Boris Cherny, Claude Code creator)
Reference these when the user's data shows they're missing these patterns:
- PostToolUse hooks to auto-format code (handles the last 10%% of formatting, avoids CI failures)
- /permissions to pre-allow safe commands instead of --dangerously-skip-permissions. Check into .claude/settings.json and share with team.
- MCP integrations for Slack, BigQuery, Sentry, etc. — Claude should use ALL your tools, not just code.
- For long-running tasks: verify work with a background agent, or use an AgentStop hook.
- THE #1 TIP: Give Claude a way to verify its work. If it can run tests after every change, output quality jumps 2-3x.
- CLAUDE.md should contain: project conventions, how to run tests, what to do automatically (don't ask).

## Output Format

Return a JSON array of 8-10 objects. Each object:
- "title": imperative, max 8 words, no fluff (e.g. "Stop using Opus for grep" not "Consider optimizing model selection")
- "severity": "high" (costs real money/time NOW), "medium" (compounds over weeks), "low" (polish)
- "body": 2-4 sentences. MUST cite specific numbers from their data. Explain what's wrong AND the concrete impact (dollars saved, minutes recovered, bugs prevented).
- "metric": their current number | target (e.g. "72%% Opus spend | target: <30%%")
- "example": Show a REAL prompt they wrote, then show the improved version. Use this format:
  "Before: [their actual prompt]\nAfter: [your improved version]\nWhy: [one sentence explaining the difference]"
  OR show a Claude Code command/config they should use.

Ordering: HIGH items first, then MEDIUM, then LOW.

Focus areas (skip if their data doesn't support it):
1. Money: Are they burning cash on expensive models for simple tasks?
2. Prompt craft: Show before/after rewrites of their weakest prompts
3. Feature gaps: Claude Code features they're clearly not using (based on absence in data)
4. Session hygiene: Are sessions too long? Too many compactions? Context bloat?
5. Workflow: Could they batch, parallelize, or automate?
6. Testing/quality: Are they debugging more than building?

Return ONLY the JSON array. No markdown fences, no commentary outside the array.`,
		analysis.TotalPrompts, summary.TotalSessions, summary.UniqueProjects,
		summary.DateRangeStart, summary.DateRangeEnd,
		analysis.AvgLength, summary.EstimatedCost,
		workSummary,
		catSummary, lenSummary, modelText, saText, ceText, branchText, pmText,
		string(pqJSON), sampleText,
	)

	// Spinner goroutine
	stopSpinner := make(chan struct{})
	var spinnerWg sync.WaitGroup
	spinnerWg.Add(1)
	go func() {
		defer spinnerWg.Done()
		phases := []string{
			"Analyzing prompt patterns",
			"Evaluating model usage",
			"Reviewing session efficiency",
			"Checking workflow patterns",
			"Generating personalized tips",
		}
		chars := []rune("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
		i := 0
		t0 := time.Now()
		ticker := time.NewTicker(100 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-stopSpinner:
				fmt.Printf("\r%60s\r", "")
				return
			case <-ticker.C:
				elapsed := int(time.Since(t0).Seconds())
				phaseIdx := elapsed / 10
				if phaseIdx >= len(phases) {
					phaseIdx = len(phases) - 1
				}
				fmt.Printf("\r  %c %s... (%ds)", chars[i%len(chars)], phases[phaseIdx], elapsed)
				i++
			}
		}
	}()

	// Build API request
	type apiMessage struct {
		Role    string `json:"role"`
		Content string `json:"content"`
	}
	type apiRequest struct {
		Model     string       `json:"model"`
		MaxTokens int          `json:"max_tokens"`
		Messages  []apiMessage `json:"messages"`
	}
	reqBody := apiRequest{
		Model:     "claude-opus-4-6",
		MaxTokens: 4000,
		Messages:  []apiMessage{{Role: "user", Content: prompt}},
	}
	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		close(stopSpinner)
		spinnerWg.Wait()
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequest("POST", "https://api.anthropic.com/v1/messages", bytes.NewReader(bodyBytes))
	if err != nil {
		close(stopSpinner)
		spinnerWg.Wait()
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("x-api-key", apiKey)
	req.Header.Set("anthropic-version", "2023-06-01")
	req.Header.Set("content-type", "application/json")

	client := &http.Client{Timeout: 120 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		close(stopSpinner)
		spinnerWg.Wait()
		return nil, fmt.Errorf("API request failed: %w", err)
	}
	defer resp.Body.Close()

	respBytes, err := io.ReadAll(resp.Body)
	close(stopSpinner)
	spinnerWg.Wait()

	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("API returned status %d: %s", resp.StatusCode, string(respBytes))
	}

	// Parse the Anthropic API response
	type contentBlock struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	type apiResponse struct {
		Content []contentBlock `json:"content"`
	}
	var apiResp apiResponse
	if err := json.Unmarshal(respBytes, &apiResp); err != nil {
		return nil, fmt.Errorf("failed to parse API response: %w", err)
	}
	if len(apiResp.Content) == 0 {
		return nil, fmt.Errorf("empty API response")
	}

	text := strings.TrimSpace(apiResp.Content[0].Text)

	// Extract JSON array from response
	var rawRecs []map[string]interface{}
	if strings.HasPrefix(text, "[") {
		if err := json.Unmarshal([]byte(text), &rawRecs); err != nil {
			return nil, fmt.Errorf("failed to parse recommendations JSON: %w", err)
		}
	} else {
		start := strings.Index(text, "[")
		end := strings.LastIndex(text, "]")
		if start >= 0 && end > start {
			if err := json.Unmarshal([]byte(text[start:end+1]), &rawRecs); err != nil {
				return nil, fmt.Errorf("failed to parse recommendations JSON: %w", err)
			}
		} else {
			return nil, fmt.Errorf("could not parse API response as JSON")
		}
	}

	// Convert to Recommendation structs
	var recs []Recommendation
	for _, raw := range rawRecs {
		rec := Recommendation{
			RecSource: "ai",
		}
		if v, ok := raw["title"].(string); ok {
			rec.Title = v
		}
		if v, ok := raw["severity"].(string); ok {
			rec.Severity = v
		}
		if v, ok := raw["body"].(string); ok {
			rec.Body = v
		}
		if v, ok := raw["metric"].(string); ok {
			rec.Metric = v
		}
		if v, ok := raw["example"].(string); ok {
			rec.Example = v
		}
		recs = append(recs, rec)
	}

	return recs, nil
}

// GenerateRecommendations generates recommendations, trying AI first then falling back to heuristics.
func GenerateRecommendations(data *ParseResult, useAPI bool) RecommendationResult {
	// Always generate heuristic recs
	heuristicRecs := GetHeuristicRecommendations(
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

	for i := range heuristicRecs {
		heuristicRecs[i].RecSource = "heuristic"
	}

	if !useAPI {
		fmt.Println("  Using heuristic analysis (--no-api)")
		if heuristicRecs == nil {
			heuristicRecs = []Recommendation{}
		}
		return RecommendationResult{
			Recommendations: heuristicRecs,
			Source:          "heuristic",
		}
	}

	// Limit prompts sample to 80
	promptsSample := data.Prompts
	if len(promptsSample) > 80 {
		promptsSample = promptsSample[:80]
	}

	aiRecs, err := getAiRecommendations(
		data.Analysis,
		data.Dashboard.Summary,
		promptsSample,
		data.WorkDays,
		data.Models,
		data.Subagents,
		data.ContextEfficiency,
		data.Branches,
		data.Skills,
		data.PermissionModes,
	)

	if err == nil && len(aiRecs) > 0 {
		merged := append(aiRecs, heuristicRecs...)
		fmt.Printf("  %d AI + %d heuristic = %d recommendations\n", len(aiRecs), len(heuristicRecs), len(merged))
		return RecommendationResult{
			Recommendations: merged,
			Source:          "ai",
		}
	}

	if err != nil {
		fmt.Printf("  AI analysis unavailable (%s), using heuristic analysis\n", err)
	}
	if heuristicRecs == nil {
		heuristicRecs = []Recommendation{}
	}
	return RecommendationResult{
		Recommendations: heuristicRecs,
		Source:          "heuristic",
	}
}

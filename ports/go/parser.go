package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

// Pre-compiled regex cache for hasWord to avoid recompilation in hot loops.
var wordRegexCache sync.Map

// Pre-compiled confirmation regex for CategorizePrompt.
var confirmRe = regexp.MustCompile(`^(y(es)?|yeah|yep|ok(ay)?|sure|go|do it|proceed|looks good|lgtm|correct|right|confirm|approved|continue|k|yea|np|go ahead|ship it|perfect|great|nice|good|cool|thanks|ty|thx)\s*$`)

// === COST ESTIMATES (per million tokens, USD) ===

type CostTier struct {
	Input      float64
	Output     float64
	CacheRead  float64
	CacheWrite float64
}

var ModelCosts = map[string]CostTier{
	"claude-opus-4":   {Input: 15.0, Output: 75.0, CacheRead: 1.5, CacheWrite: 18.75},
	"claude-sonnet-4": {Input: 3.0, Output: 15.0, CacheRead: 0.30, CacheWrite: 3.75},
	"claude-haiku-4":  {Input: 0.80, Output: 4.0, CacheRead: 0.08, CacheWrite: 1.0},
}

// MatchModelCost matches a model string to its cost tier.
func MatchModelCost(modelStr string) CostTier {
	m := strings.ToLower(modelStr)
	if strings.Contains(m, "opus") {
		return ModelCosts["claude-opus-4"]
	}
	if strings.Contains(m, "sonnet") {
		return ModelCosts["claude-sonnet-4"]
	}
	if strings.Contains(m, "haiku") {
		return ModelCosts["claude-haiku-4"]
	}
	return ModelCosts["claude-sonnet-4"]
}

// DetectTimezoneOffset detects the local timezone offset from UTC in hours.
func DetectTimezoneOffset() int {
	_, offset := time.Now().Zone()
	return offset / 3600
}

// FindClaudeDir finds the ~/.claude directory.
func FindClaudeDir() (string, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return "", fmt.Errorf("cannot find home directory: %w", err)
	}
	claudeDir := filepath.Join(home, ".claude")
	if _, err := os.Stat(claudeDir); os.IsNotExist(err) {
		return "", fmt.Errorf("Claude directory not found at %s\nMake sure you have Claude Code installed and have used it at least once", claudeDir)
	}
	return claudeDir, nil
}

// FindSessionFiles finds all main session JSONL files (excluding subagents).
func FindSessionFiles(claudeDir string) ([]string, error) {
	projectsDir := filepath.Join(claudeDir, "projects")
	if _, err := os.Stat(projectsDir); os.IsNotExist(err) {
		return nil, fmt.Errorf("no projects directory found at %s", projectsDir)
	}

	pattern := filepath.Join(projectsDir, "*", "*.jsonl")
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return nil, err
	}

	var mainSessions []string
	for _, f := range matches {
		if !strings.Contains(f, "subagent") {
			mainSessions = append(mainSessions, f)
		}
	}
	return mainSessions, nil
}

// FindSubagentFiles finds all subagent JSONL and meta files.
func FindSubagentFiles(claudeDir string) (jsonlFiles []string, metaFiles []string) {
	projectsDir := filepath.Join(claudeDir, "projects")
	if _, err := os.Stat(projectsDir); os.IsNotExist(err) {
		return nil, nil
	}

	jsonlPattern := filepath.Join(projectsDir, "*", "*", "subagents", "*.jsonl")
	jsonlFiles, _ = filepath.Glob(jsonlPattern)

	metaPattern := filepath.Join(projectsDir, "*", "*", "subagents", "*.meta.json")
	metaFiles, _ = filepath.Glob(metaPattern)

	return
}

// CleanProjectName converts directory name to readable project name.
func CleanProjectName(dirname string) string {
	name := dirname
	home, _ := os.UserHomeDir()
	homeSafe := strings.ReplaceAll(home, "/", "-")
	homeSafe = strings.ReplaceAll(homeSafe, "\\", "-")
	if strings.HasPrefix(homeSafe, "-") {
		homeSafe = homeSafe[1:]
	}
	name = strings.ReplaceAll(name, homeSafe+"-", "")
	name = strings.ReplaceAll(name, homeSafe, "home")
	if strings.HasPrefix(name, "-") {
		name = name[1:]
	}
	if name == "" {
		return "unknown"
	}
	return name
}

// NormalizeModelName normalizes model string to a clean display name.
func NormalizeModelName(modelStr string) string {
	if modelStr == "" {
		return "unknown"
	}
	m := strings.ToLower(modelStr)
	if strings.Contains(m, "opus") {
		return "Opus"
	}
	if strings.Contains(m, "sonnet") {
		return "Sonnet"
	}
	if strings.Contains(m, "haiku") {
		return "Haiku"
	}
	return modelStr
}

// hasWord checks if any word from the list appears as a whole word in text.
func hasWord(words []string, text string) bool {
	for _, w := range words {
		pattern := `\b` + regexp.QuoteMeta(w) + `\b`
		if cached, ok := wordRegexCache.Load(pattern); ok {
			if cached.(*regexp.Regexp).MatchString(text) {
				return true
			}
			continue
		}
		re, err := regexp.Compile(pattern)
		if err != nil {
			continue
		}
		wordRegexCache.Store(pattern, re)
		if re.MatchString(text) {
			return true
		}
	}
	return false
}

// CategorizePrompt categorizes a user prompt by intent.
func CategorizePrompt(text string) string {
	t := strings.TrimSpace(strings.ToLower(text))
	if len(t) < 5 {
		return "micro"
	}

	if confirmRe.MatchString(t) {
		return "confirmation"
	}

	if hasWord([]string{
		"error", "bug", "fix", "broken", "crash", "fail", "issue",
		"wrong", "not working", "doesn't work", "won't", "undefined",
		"null", "exception", "traceback",
	}, t) {
		return "debugging"
	}

	if hasWord([]string{
		"add", "create", "build", "implement", "make", "new feature",
		"set up", "setup", "write", "generate",
	}, t) {
		return "building"
	}

	if hasWord([]string{
		"refactor", "clean up", "rename", "move", "restructure",
		"reorganize", "simplify", "extract",
	}, t) {
		return "refactoring"
	}

	questionPrefixes := []string{
		"how", "what", "why", "where", "when", "can you", "is there",
		"do we", "does", "which", "should",
	}
	for _, p := range questionPrefixes {
		if strings.HasPrefix(t, p) {
			return "question"
		}
	}

	if hasWord([]string{
		"review", "check", "look at", "examine", "inspect", "analyze",
		"show me", "read", "list", "find",
	}, t) {
		return "review"
	}

	if hasWord([]string{
		"update", "change", "modify", "edit", "replace", "remove",
		"delete", "tweak", "adjust",
	}, t) {
		return "editing"
	}

	if hasWord([]string{"test", "spec", "coverage", "assert", "expect"}, t) {
		return "testing"
	}

	if hasWord([]string{
		"commit", "push", "deploy", "merge", "branch", "pr ",
		"pull request", "git ",
	}, t) {
		return "git_ops"
	}

	if len(t) < 30 {
		return "brief"
	}

	return "detailed"
}

// LengthBucket classifies prompt length into a bucket.
func LengthBucket(length int) string {
	if length < 20 {
		return "micro (<20)"
	}
	if length < 50 {
		return "short (20-50)"
	}
	if length < 150 {
		return "medium (50-150)"
	}
	if length < 500 {
		return "detailed (150-500)"
	}
	return "comprehensive (500+)"
}

// === Data structures ===

type Prompt struct {
	Text         string `json:"text"`
	FullLength   int    `json:"full_length"`
	Project      string `json:"project"`
	SessionID    string `json:"session_id"`
	Date         string `json:"date"`
	Time         string `json:"time"`
	Hour         int    `json:"hour"`
	Weekday      int    `json:"weekday"`
	Category     string `json:"category"`
	LengthBucket string `json:"length_bucket"`
}

type Message struct {
	Timestamp    string   `json:"timestamp"`
	Date         string   `json:"date"`
	Time         string   `json:"time,omitempty"`
	Hour         int      `json:"hour"`
	Weekday      int      `json:"weekday"`
	WeekdayName  string   `json:"weekday_name,omitempty"`
	Month        string   `json:"month,omitempty"`
	Type         string   `json:"type"`
	Project      string   `json:"project"`
	SessionID    string   `json:"session_id"`
	ToolUses     []string `json:"tool_uses,omitempty"`
	InputTokens  int      `json:"input_tokens,omitempty"`
	OutputTokens int      `json:"output_tokens,omitempty"`
	Model        string   `json:"model,omitempty"`
}

type SessionMeta struct {
	Project         string
	SessionID       string
	FirstTS         string
	LastTS          string
	UserMsgs        int
	AssistantMsgs   int
	ToolUses        int
	Model           string
	Entrypoint      string
	MsgCount        int
	GitBranch       string
	InputTokens     int
	OutputTokens    int
	CacheReadTokens int
	CacheWriteTokens int
}

type DrilldownEntry struct {
	Time     string `json:"time"`
	Text     string `json:"text"`
	Category string `json:"category"`
	Length   int    `json:"length"`
}

type DailyData struct {
	Date          string `json:"date"`
	UserMsgs      int    `json:"user_msgs"`
	AssistantMsgs int    `json:"assistant_msgs"`
	ToolCalls     int    `json:"tool_calls"`
	OutputTokens  int    `json:"output_tokens"`
	TotalMsgs     int    `json:"total_msgs"`
}

type HeatmapCell struct {
	Weekday int `json:"weekday"`
	Hour    int `json:"hour"`
	Count   int `json:"count"`
}

type ProjectData struct {
	Project       string `json:"project"`
	UserMsgs      int    `json:"user_msgs"`
	AssistantMsgs int    `json:"assistant_msgs"`
	ToolCalls     int    `json:"tool_calls"`
	Sessions      int    `json:"sessions"`
	OutputTokens  int    `json:"output_tokens"`
	TotalMsgs     int    `json:"total_msgs"`
}

type ToolData struct {
	Tool  string `json:"tool"`
	Count int    `json:"count"`
}

type HourlyData struct {
	Hour  int `json:"hour"`
	Count int `json:"count"`
}

type SessionDuration struct {
	SessionID     string  `json:"session_id"`
	Project       string  `json:"project"`
	DurationMin   float64 `json:"duration_min"`
	UserMsgs      int     `json:"user_msgs"`
	AssistantMsgs int     `json:"assistant_msgs"`
	ToolUses      int     `json:"tool_uses"`
	Date          string  `json:"date"`
	StartHour     int     `json:"start_hour"`
	MsgsPerMin    float64 `json:"msgs_per_min"`
	GitBranch     string  `json:"git_branch"`
}

type WeeklyData struct {
	Week     string `json:"week"`
	UserMsgs int    `json:"user_msgs"`
	Sessions int    `json:"sessions"`
}

type EfficiencyData struct {
	Hour              int     `json:"hour"`
	AvgMsgsPerSession float64 `json:"avg_msgs_per_session"`
	AvgDuration       float64 `json:"avg_duration"`
	Sessions          int     `json:"sessions"`
}

type WorkDay struct {
	Date      string  `json:"date"`
	First     string  `json:"first"`
	Last      string  `json:"last"`
	SpanHrs   float64 `json:"span_hrs"`
	ActiveHrs float64 `json:"active_hrs"`
	Prompts   int     `json:"prompts"`
}

type CategoryStat struct {
	Cat   string  `json:"cat"`
	Count int     `json:"count"`
	Pct   float64 `json:"pct"`
}

type LengthBucketStat struct {
	Bucket string  `json:"bucket"`
	Count  int     `json:"count"`
	Pct    float64 `json:"pct"`
}

type ProjectQuality struct {
	Project     string  `json:"project"`
	Count       int     `json:"count"`
	AvgLen      int     `json:"avg_len"`
	ConfirmPct  float64 `json:"confirm_pct"`
	DetailedPct float64 `json:"detailed_pct"`
	TopCat      string  `json:"top_cat"`
}

type Analysis struct {
	TotalPrompts   int                `json:"total_prompts"`
	AvgLength      int                `json:"avg_length"`
	Categories     []CategoryStat     `json:"categories"`
	LengthBuckets  []LengthBucketStat `json:"length_buckets"`
	ProjectQuality []ProjectQuality   `json:"project_quality"`
}

type ModelBreakdown struct {
	Model           string  `json:"model"`
	Display         string  `json:"display"`
	Msgs            int     `json:"msgs"`
	InputTokens     int     `json:"input_tokens"`
	OutputTokens    int     `json:"output_tokens"`
	CacheReadTokens int     `json:"cache_read_tokens"`
	CacheWriteTokens int    `json:"cache_write_tokens"`
	EstimatedCost   float64 `json:"estimated_cost"`
}

type SubagentEntry struct {
	AgentID         string   `json:"agent_id"`
	Type            string   `json:"type"`
	Description     string   `json:"description"`
	IsCompaction    bool     `json:"is_compaction"`
	Project         string   `json:"project"`
	Messages        int      `json:"messages"`
	ToolCalls       int      `json:"tool_calls"`
	InputTokens     int      `json:"input_tokens"`
	OutputTokens    int      `json:"output_tokens"`
	CacheReadTokens int      `json:"cache_read_tokens"`
	Models          []string `json:"models"`
	DurationMin     float64  `json:"duration_min"`
}

type SubagentData struct {
	Subagents                []SubagentEntry    `json:"subagents"`
	TypeCounts               map[string]int     `json:"type_counts"`
	TotalCount               int                `json:"total_count"`
	CompactionCount          int                `json:"compaction_count"`
	TotalSubagentInputTokens int               `json:"total_subagent_input_tokens"`
	TotalSubagentOutputTokens int              `json:"total_subagent_output_tokens"`
	ModelTokens              map[string]map[string]int `json:"model_tokens"`
	EstimatedCost            float64            `json:"estimated_cost"`
}

type BranchData struct {
	Branch   string   `json:"branch"`
	Msgs     int      `json:"msgs"`
	Sessions int      `json:"sessions"`
	Projects []string `json:"projects"`
}

type ContextEfficiency struct {
	ToolOutputTokens     int     `json:"tool_output_tokens"`
	ConversationTokens   int     `json:"conversation_tokens"`
	ToolPct              float64 `json:"tool_pct"`
	ConversationPct      float64 `json:"conversation_pct"`
	ThinkingBlocks       int     `json:"thinking_blocks"`
	SubagentOutputTokens int     `json:"subagent_output_tokens"`
	SubagentPct          float64 `json:"subagent_pct"`
}

type VersionData struct {
	Version string `json:"version"`
	Count   int    `json:"count"`
}

type SkillData struct {
	Skill string `json:"skill"`
	Count int    `json:"count"`
}

type SlashCommandData struct {
	Command string `json:"command"`
	Count   int    `json:"count"`
}

type Config struct {
	HasConfig    bool                     `json:"has_config"`
	Plugins      []string                 `json:"plugins"`
	FeatureFlags []map[string]interface{} `json:"feature_flags"`
	VersionInfo  map[string]string        `json:"version_info"`
}

type Summary struct {
	TotalSessions        int     `json:"total_sessions"`
	TotalUserMsgs        int     `json:"total_user_msgs"`
	TotalAssistantMsgs   int     `json:"total_assistant_msgs"`
	TotalToolCalls       int     `json:"total_tool_calls"`
	TotalOutputTokens    int     `json:"total_output_tokens"`
	TotalInputTokens     int     `json:"total_input_tokens"`
	TotalCacheReadTokens int     `json:"total_cache_read_tokens"`
	TotalCacheWriteTokens int    `json:"total_cache_write_tokens"`
	DateRangeStart       string  `json:"date_range_start"`
	DateRangeEnd         string  `json:"date_range_end"`
	SinceDate            string  `json:"since_date"`
	UniqueProjects       int     `json:"unique_projects"`
	UniqueTools          int     `json:"unique_tools"`
	AvgSessionDuration   float64 `json:"avg_session_duration"`
	TzOffset             int     `json:"tz_offset"`
	TzLabel              string  `json:"tz_label"`
	EstimatedCost        float64 `json:"estimated_cost"`
	SkippedFiles         int     `json:"skipped_files"`
	SkippedLines         int     `json:"skipped_lines"`
}

type Dashboard struct {
	Summary    Summary           `json:"summary"`
	Daily      []DailyData       `json:"daily"`
	Heatmap    []HeatmapCell     `json:"heatmap"`
	Projects   []ProjectData     `json:"projects"`
	Tools      []ToolData        `json:"tools"`
	Hourly     []HourlyData      `json:"hourly"`
	Sessions   []SessionDuration `json:"sessions"`
	Weekly     []WeeklyData      `json:"weekly"`
	Efficiency []EfficiencyData  `json:"efficiency"`
}

type ParseResult struct {
	Dashboard         Dashboard                               `json:"dashboard"`
	Drilldown         map[string]map[string][]DrilldownEntry   `json:"drilldown"`
	Analysis          Analysis                                 `json:"analysis"`
	Prompts           []Prompt                                 `json:"prompts"`
	WorkDays          []WorkDay                                `json:"work_days"`
	Models            []ModelBreakdown                         `json:"models"`
	Subagents         SubagentData                             `json:"subagents"`
	Branches          []BranchData                             `json:"branches"`
	ContextEfficiency ContextEfficiency                        `json:"context_efficiency"`
	Versions          []VersionData                            `json:"versions"`
	Skills            []SkillData                              `json:"skills"`
	SlashCommands     []SlashCommandData                       `json:"slash_commands"`
	PermissionModes   map[string]int                           `json:"permission_modes"`
	Config            Config                                   `json:"config"`
}

// ParseConfig parses .claude.json for feature flags, plugins, and settings.
func ParseConfig(claudeDir string) Config {
	configPath := filepath.Join(claudeDir, ".claude.json")
	config := Config{
		Plugins:      []string{},
		FeatureFlags: []map[string]interface{}{},
		VersionInfo:  map[string]string{},
	}

	data, err := os.ReadFile(configPath)
	if err != nil {
		return config
	}

	var raw map[string]interface{}
	if err := json.Unmarshal(data, &raw); err != nil {
		return config
	}

	config.HasConfig = true

	// Extract plugins from feature flags
	if features, ok := raw["cachedGrowthBookFeatures"].(map[string]interface{}); ok {
		if amberLattice, ok := features["tengu_amber_lattice"].(map[string]interface{}); ok {
			if plugins, ok := amberLattice["value"].([]interface{}); ok {
				for _, p := range plugins {
					if s, ok := p.(string); ok {
						config.Plugins = append(config.Plugins, s)
					}
				}
			}
		}

		// Extract interesting feature flags
		for key, val := range features {
			flagName := strings.ReplaceAll(key, "tengu_", "")
			switch v := val.(type) {
			case map[string]interface{}:
				enabled := false
				if bv, ok := v["value"]; ok {
					enabled = bv != nil && bv != false && bv != 0 && bv != ""
				}
				config.FeatureFlags = append(config.FeatureFlags, map[string]interface{}{
					"name":    flagName,
					"enabled": enabled,
				})
			case bool:
				config.FeatureFlags = append(config.FeatureFlags, map[string]interface{}{
					"name":    flagName,
					"enabled": v,
				})
			}
		}
	}

	// Migration / account info
	vi := map[string]string{}
	if mv, ok := raw["migrationVersion"]; ok {
		vi["migration_version"] = fmt.Sprintf("%v", mv)
	}
	if fs, ok := raw["firstStartTime"]; ok {
		vi["first_start"] = fmt.Sprintf("%v", fs)
	}
	config.VersionInfo = vi

	return config
}

// ParseSubagents parses all subagent data.
func ParseSubagents(claudeDir string, tzOffset int) SubagentData {
	jsonlFiles, metaFiles := FindSubagentFiles(claudeDir)

	// Build meta lookup
	metaLookup := map[string]map[string]string{}
	for _, mf := range metaFiles {
		data, err := os.ReadFile(mf)
		if err != nil {
			continue
		}
		var meta map[string]interface{}
		if err := json.Unmarshal(data, &meta); err != nil {
			continue
		}
		base := filepath.Base(mf)
		agentID := strings.TrimSuffix(strings.TrimPrefix(base, "agent-"), ".meta.json")
		agentType := "unknown"
		if at, ok := meta["agentType"].(string); ok {
			agentType = at
		}
		desc := ""
		if d, ok := meta["description"].(string); ok {
			desc = d
		}
		metaLookup[agentID] = map[string]string{"type": agentType, "description": desc}
	}

	var subagents []SubagentEntry
	typeCounts := map[string]int{}
	modelTokens := map[string]map[string]int{}

	for _, fp := range jsonlFiles {
		base := filepath.Base(fp)
		agentID := strings.TrimSuffix(strings.TrimPrefix(base, "agent-"), ".jsonl")
		isCompaction := strings.Contains(strings.ToLower(agentID), "compact")
		meta, ok := metaLookup[agentID]
		if !ok {
			meta = map[string]string{"type": "unknown", "description": ""}
		}
		agentType := meta["type"]
		typeCounts[agentType]++

		msgCount := 0
		toolCalls := 0
		inputTokens := 0
		outputTokens := 0
		cacheRead := 0
		modelsUsed := map[string]bool{}
		var firstTS, lastTS string

		file, err := os.Open(fp)
		if err != nil {
			continue
		}

		scanner := bufio.NewScanner(file)
		scanner.Buffer(make([]byte, 1024*1024), 1024*1024)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" {
				continue
			}
			var d map[string]interface{}
			if err := json.Unmarshal([]byte(line), &d); err != nil {
				continue
			}

			if ts, ok := d["timestamp"].(string); ok && ts != "" {
				if firstTS == "" || ts < firstTS {
					firstTS = ts
				}
				if lastTS == "" || ts > lastTS {
					lastTS = ts
				}
			}

			if msg, ok := d["message"].(map[string]interface{}); ok {
				if m, ok := msg["model"].(string); ok && m != "" {
					modelsUsed[m] = true
				}
				if usage, ok := msg["usage"].(map[string]interface{}); ok {
					inputTokens += intFromInterface(usage["input_tokens"])
					outputTokens += intFromInterface(usage["output_tokens"])
					cacheRead += intFromInterface(usage["cache_read_input_tokens"])
				}
				if content, ok := msg["content"].([]interface{}); ok {
					for _, c := range content {
						if cm, ok := c.(map[string]interface{}); ok {
							if cm["type"] == "tool_use" {
								toolCalls++
							}
						}
					}
				}
			}
			msgCount++
		}
		file.Close()

		// Get parent project
		parentSessionDir := filepath.Base(filepath.Dir(filepath.Dir(filepath.Dir(fp))))
		projName := CleanProjectName(parentSessionDir)

		duration := 0.0
		if firstTS != "" && lastTS != "" {
			t1 := parseTimestamp(firstTS)
			t2 := parseTimestamp(lastTS)
			if !t1.IsZero() && !t2.IsZero() {
				duration = t2.Sub(t1).Minutes()
			}
		}

		models := make([]string, 0, len(modelsUsed))
		for m := range modelsUsed {
			models = append(models, m)
		}

		truncID := agentID
		if len(truncID) > 12 {
			truncID = truncID[:12]
		}
		desc := meta["description"]
		if len(desc) > 80 {
			desc = desc[:80]
		}

		subagents = append(subagents, SubagentEntry{
			AgentID:         truncID,
			Type:            agentType,
			Description:     desc,
			IsCompaction:    isCompaction,
			Project:         projName,
			Messages:        msgCount,
			ToolCalls:       toolCalls,
			InputTokens:     inputTokens,
			OutputTokens:    outputTokens,
			CacheReadTokens: cacheRead,
			Models:          models,
			DurationMin:     math.Round(duration*10) / 10,
		})

		// Accumulate tokens by model for subagents
		numModels := maxInt(len(modelsUsed), 1)
		for m := range modelsUsed {
			if _, ok := modelTokens[m]; !ok {
				modelTokens[m] = map[string]int{"input": 0, "output": 0, "cache_read": 0}
			}
			modelTokens[m]["input"] += inputTokens / numModels
			modelTokens[m]["output"] += outputTokens / numModels
			modelTokens[m]["cache_read"] += cacheRead / numModels
		}
	}

	if subagents == nil {
		subagents = []SubagentEntry{}
	}

	totalInputTokens := 0
	totalOutputTokens := 0
	compactionCount := 0
	for _, s := range subagents {
		totalInputTokens += s.InputTokens
		totalOutputTokens += s.OutputTokens
		if s.IsCompaction {
			compactionCount++
		}
	}

	return SubagentData{
		Subagents:                 subagents,
		TypeCounts:                typeCounts,
		TotalCount:                len(subagents),
		CompactionCount:           compactionCount,
		TotalSubagentInputTokens:  totalInputTokens,
		TotalSubagentOutputTokens: totalOutputTokens,
		ModelTokens:               modelTokens,
	}
}

func parseTimestamp(ts string) time.Time {
	ts = strings.ReplaceAll(ts, "Z", "+00:00")
	// Try parsing with timezone
	t, err := time.Parse(time.RFC3339, ts)
	if err != nil {
		// Try alternate format
		t, err = time.Parse("2006-01-02T15:04:05.000-07:00", ts)
		if err != nil {
			// Try without fractional seconds
			t, _ = time.Parse("2006-01-02T15:04:05-07:00", ts)
		}
	}
	return t
}

func intFromInterface(v interface{}) int {
	switch n := v.(type) {
	case float64:
		return int(n)
	case int:
		return n
	case int64:
		return int(n)
	}
	return 0
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

func truncateStr(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// ParseAllSessions parses all session data and returns structured analytics.
func ParseAllSessions(claudeDir string, tzOffset *int, sinceDate string) (*ParseResult, error) {
	offset := 0
	if tzOffset != nil {
		offset = *tzOffset
	} else {
		offset = DetectTimezoneOffset()
	}

	sessionFiles, err := FindSessionFiles(claudeDir)
	if err != nil {
		return nil, err
	}
	if len(sessionFiles) == 0 {
		return nil, fmt.Errorf("no session files found. Use Claude Code for a while first")
	}

	// === Pass 1: Extract all messages ===
	var allMessages []Message
	var sessionsMeta []SessionMeta
	var prompts []Prompt
	drilldown := map[string]map[string][]DrilldownEntry{}
	skippedFiles := 0
	skippedLines := 0

	// Track models, branches, versions, thinking blocks, cost
	type modelCount struct {
		msgs, input, output, cacheRead, cacheWrite int
	}
	modelCounts := map[string]*modelCount{}
	type branchAct struct {
		msgs     int
		sessions map[string]bool
		projects map[string]bool
	}
	branchActivity := map[string]*branchAct{}
	versionCounts := map[string]int{}
	thinkingCount := 0
	totalToolResultTokens := 0
	totalConversationTokens := 0
	skillUsage := map[string]int{}
	slashCommands := map[string]int{}
	permissionModes := map[string]int{}

	loc := time.FixedZone("custom", offset*3600)

	for _, fp := range sessionFiles {
		projectDir := filepath.Base(filepath.Dir(fp))
		projName := CleanProjectName(projectDir)
		sessionID := strings.TrimSuffix(filepath.Base(fp), ".jsonl")

		var timestamps []string
		userMsgs := 0
		assistantMsgs := 0
		toolUses := 0
		model := ""
		entrypoint := ""
		gitBranch := ""
		sessionInputTokens := 0
		sessionOutputTokens := 0
		sessionCacheRead := 0
		sessionCacheWrite := 0

		file, err := os.Open(fp)
		if err != nil {
			skippedFiles++
			continue
		}

		scanner := bufio.NewScanner(file)
		scanner.Buffer(make([]byte, 1024*1024), 1024*1024)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" {
				continue
			}
			var d map[string]interface{}
			if err := json.Unmarshal([]byte(line), &d); err != nil {
				skippedLines++
				continue
			}

			msgType, _ := d["type"].(string)
			ts, _ := d["timestamp"].(string)

			// Track version, branch, permission mode
			if ver, ok := d["version"].(string); ok && ver != "" {
				versionCounts[ver]++
			}
			if br, ok := d["gitBranch"].(string); ok && br != "" && br != "HEAD" {
				gitBranch = br
			}
			if pm, ok := d["permissionMode"].(string); ok && pm != "" {
				permissionModes[pm]++
			}

			if msgType == "user" && ts != "" {
				t := parseTimestamp(ts)
				if t.IsZero() {
					continue
				}
				dt := t.In(loc)

				// Skip messages before the since_date cutoff
				dateStr := dt.Format("2006-01-02")
				if sinceDate != "" && dateStr < sinceDate {
					continue
				}

				userMsgs++
				if entrypoint == "" {
					if ep, ok := d["entrypoint"].(string); ok {
						entrypoint = ep
					}
				}

				msgData := Message{
					Timestamp:   ts,
					Date:        dateStr,
					Time:        dt.Format("15:04"),
					Hour:        dt.Hour(),
					Weekday:     int(dt.Weekday()+6) % 7, // Monday=0
					WeekdayName: dt.Weekday().String(),
					Month:       dt.Format("2006-01"),
					Type:        "user",
					Project:     projName,
					SessionID:   truncateStr(sessionID, 8),
				}
				allMessages = append(allMessages, msgData)
				timestamps = append(timestamps, ts)

				// Extract prompt text
				text := ""
				isToolResult := false

				if msg, ok := d["message"].(map[string]interface{}); ok {
					content := msg["content"]
					switch c := content.(type) {
					case string:
						text = strings.TrimSpace(c)
					case []interface{}:
						hasText := false
						for _, item := range c {
							if cm, ok := item.(map[string]interface{}); ok {
								if cm["type"] == "text" {
									if t, ok := cm["text"].(string); ok && strings.TrimSpace(t) != "" {
										text += t + " "
										hasText = true
									}
								} else if cm["type"] == "tool_result" {
									isToolResult = true
								}
							}
						}
						text = strings.TrimSpace(text)
						if !hasText && isToolResult {
							text = ""
						}
					}
				}

				if text != "" {
					prompt := Prompt{
						Text:         truncateStr(text, 500),
						FullLength:   len(text),
						Project:      projName,
						SessionID:    truncateStr(sessionID, 8),
						Date:         dateStr,
						Time:         dt.Format("15:04"),
						Hour:         dt.Hour(),
						Weekday:      int(dt.Weekday()+6) % 7,
						Category:     CategorizePrompt(text),
						LengthBucket: LengthBucket(len(text)),
					}
					prompts = append(prompts, prompt)

					if drilldown[prompt.Date] == nil {
						drilldown[prompt.Date] = map[string][]DrilldownEntry{}
					}
					drilldown[prompt.Date][projName] = append(
						drilldown[prompt.Date][projName],
						DrilldownEntry{
							Time:     prompt.Time,
							Text:     truncateStr(prompt.Text, 200),
							Category: prompt.Category,
							Length:   prompt.FullLength,
						},
					)

					// Track branch activity
					if gitBranch != "" {
						if branchActivity[gitBranch] == nil {
							branchActivity[gitBranch] = &branchAct{
								sessions: map[string]bool{},
								projects: map[string]bool{},
							}
						}
						branchActivity[gitBranch].msgs++
						branchActivity[gitBranch].sessions[truncateStr(sessionID, 8)] = true
						branchActivity[gitBranch].projects[projName] = true
					}
				}

			} else if msgType == "assistant" && ts != "" {
				t := parseTimestamp(ts)
				if t.IsZero() {
					continue
				}
				dt := t.In(loc)

				dateStr := dt.Format("2006-01-02")
				if sinceDate != "" && dateStr < sinceDate {
					continue
				}

				assistantMsgs++
				timestamps = append(timestamps, ts)

				var msgModel string
				var msgTools []string
				inputTokens := 0
				outputTokens := 0
				cacheReadTokens := 0
				cacheWriteTokens := 0

				if msg, ok := d["message"].(map[string]interface{}); ok {
					if m, ok := msg["model"].(string); ok && m != "" {
						msgModel = m
						model = m
					}
					if content, ok := msg["content"].([]interface{}); ok {
						for _, item := range content {
							if cm, ok := item.(map[string]interface{}); ok {
								if cm["type"] == "tool_use" {
									toolName, _ := cm["name"].(string)
									msgTools = append(msgTools, toolName)
									// Track MCP tool usage
									if strings.HasPrefix(toolName, "mcp__") {
										parts := strings.SplitN(toolName, "__", 3)
										if len(parts) >= 2 {
											skillUsage[parts[1]]++
										}
									}
									// Track slash command / skill invocations
									if toolName == "Skill" {
										if inp, ok := cm["input"].(map[string]interface{}); ok {
											if sn, ok := inp["skill"].(string); ok && sn != "" {
												slashCommands[sn]++
											}
										}
									}
								} else if cm["type"] == "thinking" {
									thinkingCount++
								}
							}
						}
						toolUses += len(msgTools)
					}
					if usage, ok := msg["usage"].(map[string]interface{}); ok {
						inputTokens = intFromInterface(usage["input_tokens"])
						outputTokens = intFromInterface(usage["output_tokens"])
						cacheReadTokens = intFromInterface(usage["cache_read_input_tokens"])
						cacheWriteTokens = intFromInterface(usage["cache_creation_input_tokens"])
					}
				}

				sessionInputTokens += inputTokens
				sessionOutputTokens += outputTokens
				sessionCacheRead += cacheReadTokens
				sessionCacheWrite += cacheWriteTokens

				// Track per-model token usage
				normModel := msgModel
				if normModel == "" {
					normModel = model
				}
				if normModel == "" {
					normModel = "unknown"
				}
				if modelCounts[normModel] == nil {
					modelCounts[normModel] = &modelCount{}
				}
				modelCounts[normModel].msgs++
				modelCounts[normModel].input += inputTokens
				modelCounts[normModel].output += outputTokens
				modelCounts[normModel].cacheRead += cacheReadTokens
				modelCounts[normModel].cacheWrite += cacheWriteTokens

				// Track tool result vs conversation tokens
				if len(msgTools) > 0 {
					totalToolResultTokens += outputTokens
				} else {
					totalConversationTokens += outputTokens
				}

				// Track branch activity for assistant msgs too
				if gitBranch != "" {
					if branchActivity[gitBranch] == nil {
						branchActivity[gitBranch] = &branchAct{
							sessions: map[string]bool{},
							projects: map[string]bool{},
						}
					}
					branchActivity[gitBranch].msgs++
				}

				allMessages = append(allMessages, Message{
					Timestamp:    ts,
					Date:         dateStr,
					Hour:         dt.Hour(),
					Weekday:      int(dt.Weekday()+6) % 7,
					Type:         "assistant",
					Project:      projName,
					SessionID:    truncateStr(sessionID, 8),
					ToolUses:     msgTools,
					InputTokens:  inputTokens,
					OutputTokens: outputTokens,
					Model:        msgModel,
				})
			}
		}
		file.Close()

		if len(timestamps) > 0 {
			sort.Strings(timestamps)
			sessionsMeta = append(sessionsMeta, SessionMeta{
				Project:          projName,
				SessionID:        truncateStr(sessionID, 8),
				FirstTS:          timestamps[0],
				LastTS:           timestamps[len(timestamps)-1],
				UserMsgs:         userMsgs,
				AssistantMsgs:    assistantMsgs,
				ToolUses:         toolUses,
				Model:            model,
				Entrypoint:       entrypoint,
				MsgCount:         userMsgs + assistantMsgs,
				GitBranch:        gitBranch,
				InputTokens:      sessionInputTokens,
				OutputTokens:     sessionOutputTokens,
				CacheReadTokens:  sessionCacheRead,
				CacheWriteTokens: sessionCacheWrite,
			})
		}
	}

	// === Pass 2: Aggregate ===
	var userMessages, asstMessages []Message
	for _, m := range allMessages {
		if m.Type == "user" {
			userMessages = append(userMessages, m)
		} else {
			asstMessages = append(asstMessages, m)
		}
	}

	// Daily data
	dailyUser := map[string]int{}
	dailyAsst := map[string]int{}
	dailyTools := map[string]int{}
	dailyTokens := map[string]int{}
	for _, m := range userMessages {
		dailyUser[m.Date]++
	}
	for _, m := range asstMessages {
		dailyAsst[m.Date]++
		dailyTools[m.Date] += len(m.ToolUses)
		dailyTokens[m.Date] += m.OutputTokens
	}

	dateSet := map[string]bool{}
	for d := range dailyUser {
		dateSet[d] = true
	}
	for d := range dailyAsst {
		dateSet[d] = true
	}
	allDates := make([]string, 0, len(dateSet))
	for d := range dateSet {
		allDates = append(allDates, d)
	}
	sort.Strings(allDates)

	dailyData := make([]DailyData, 0, len(allDates))
	for _, d := range allDates {
		dailyData = append(dailyData, DailyData{
			Date:          d,
			UserMsgs:      dailyUser[d],
			AssistantMsgs: dailyAsst[d],
			ToolCalls:     dailyTools[d],
			OutputTokens:  dailyTokens[d],
			TotalMsgs:     dailyUser[d] + dailyAsst[d],
		})
	}

	// Heatmap
	heatmapCounts := map[string]int{}
	for _, m := range userMessages {
		key := fmt.Sprintf("%d_%d", m.Weekday, m.Hour)
		heatmapCounts[key]++
	}
	heatmapData := make([]HeatmapCell, 0, 7*24)
	for wd := 0; wd < 7; wd++ {
		for hr := 0; hr < 24; hr++ {
			key := fmt.Sprintf("%d_%d", wd, hr)
			heatmapData = append(heatmapData, HeatmapCell{
				Weekday: wd,
				Hour:    hr,
				Count:   heatmapCounts[key],
			})
		}
	}

	// Project stats
	type projStat struct {
		userMsgs, assistantMsgs, toolCalls, outputTokens int
		sessions                                         map[string]bool
	}
	projectStats := map[string]*projStat{}
	for _, m := range allMessages {
		p := m.Project
		if projectStats[p] == nil {
			projectStats[p] = &projStat{sessions: map[string]bool{}}
		}
		ps := projectStats[p]
		ps.sessions[m.SessionID] = true
		if m.Type == "user" {
			ps.userMsgs++
		} else {
			ps.assistantMsgs++
			ps.toolCalls += len(m.ToolUses)
			ps.outputTokens += m.OutputTokens
		}
	}

	projectData := make([]ProjectData, 0, len(projectStats))
	for p, s := range projectStats {
		projectData = append(projectData, ProjectData{
			Project:       p,
			UserMsgs:      s.userMsgs,
			AssistantMsgs: s.assistantMsgs,
			ToolCalls:     s.toolCalls,
			Sessions:      len(s.sessions),
			OutputTokens:  s.outputTokens,
			TotalMsgs:     s.userMsgs + s.assistantMsgs,
		})
	}
	sort.Slice(projectData, func(i, j int) bool {
		return projectData[i].TotalMsgs > projectData[j].TotalMsgs
	})

	// Tool stats
	toolCounts := map[string]int{}
	for _, m := range asstMessages {
		for _, t := range m.ToolUses {
			toolCounts[t]++
		}
	}
	type toolCountEntry struct {
		tool  string
		count int
	}
	var toolEntries []toolCountEntry
	for t, c := range toolCounts {
		toolEntries = append(toolEntries, toolCountEntry{t, c})
	}
	sort.Slice(toolEntries, func(i, j int) bool {
		return toolEntries[i].count > toolEntries[j].count
	})
	if len(toolEntries) > 20 {
		toolEntries = toolEntries[:20]
	}
	toolData := make([]ToolData, len(toolEntries))
	for i, e := range toolEntries {
		toolData[i] = ToolData{Tool: e.tool, Count: e.count}
	}

	// Hourly
	hourlyCounts := map[int]int{}
	for _, m := range userMessages {
		hourlyCounts[m.Hour]++
	}
	hourlyData := make([]HourlyData, 24)
	for h := 0; h < 24; h++ {
		hourlyData[h] = HourlyData{Hour: h, Count: hourlyCounts[h]}
	}

	// Session durations
	var sessionDurations []SessionDuration
	for _, s := range sessionsMeta {
		t1 := parseTimestamp(s.FirstTS)
		t2 := parseTimestamp(s.LastTS)
		if t1.IsZero() || t2.IsZero() {
			continue
		}
		dur := t2.Sub(t1).Minutes()
		t1Local := t1.In(loc)
		msgsPerMin := 0.0
		if dur > 0 {
			msgsPerMin = math.Round(float64(s.MsgCount)/dur*100) / 100
		}
		sessionDurations = append(sessionDurations, SessionDuration{
			SessionID:     s.SessionID,
			Project:       s.Project,
			DurationMin:   math.Round(dur*10) / 10,
			UserMsgs:      s.UserMsgs,
			AssistantMsgs: s.AssistantMsgs,
			ToolUses:      s.ToolUses,
			Date:          t1Local.Format("2006-01-02"),
			StartHour:     t1Local.Hour(),
			MsgsPerMin:    msgsPerMin,
			GitBranch:     s.GitBranch,
		})
	}

	// Weekly
	type weeklyAgg struct {
		userMsgs int
		sessions map[string]bool
	}
	weeklyMap := map[string]*weeklyAgg{}
	for _, m := range userMessages {
		t := parseTimestamp(m.Timestamp)
		if t.IsZero() {
			continue
		}
		yr, wk := t.ISOWeek()
		week := fmt.Sprintf("%d-W%02d", yr, wk)
		if weeklyMap[week] == nil {
			weeklyMap[week] = &weeklyAgg{sessions: map[string]bool{}}
		}
		weeklyMap[week].userMsgs++
		weeklyMap[week].sessions[m.SessionID] = true
	}
	var weeklyData []WeeklyData
	for w, d := range weeklyMap {
		weeklyData = append(weeklyData, WeeklyData{
			Week:     w,
			UserMsgs: d.userMsgs,
			Sessions: len(d.sessions),
		})
	}
	sort.Slice(weeklyData, func(i, j int) bool {
		return weeklyData[i].Week < weeklyData[j].Week
	})

	// Efficiency by start hour
	type hourEff struct {
		totalMsgs, sessions int
		durationTotal       float64
	}
	hourEffMap := map[int]*hourEff{}
	for _, sd := range sessionDurations {
		h := sd.StartHour
		if hourEffMap[h] == nil {
			hourEffMap[h] = &hourEff{}
		}
		hourEffMap[h].totalMsgs += sd.UserMsgs + sd.AssistantMsgs
		hourEffMap[h].sessions++
		hourEffMap[h].durationTotal += sd.DurationMin
	}
	var efficiencyData []EfficiencyData
	for h := 0; h < 24; h++ {
		if e, ok := hourEffMap[h]; ok && e.sessions > 0 {
			efficiencyData = append(efficiencyData, EfficiencyData{
				Hour:              h,
				AvgMsgsPerSession: math.Round(float64(e.totalMsgs)/float64(e.sessions)*10) / 10,
				AvgDuration:       math.Round(e.durationTotal/float64(e.sessions)*10) / 10,
				Sessions:          e.sessions,
			})
		}
	}

	// Working hours estimate
	dailySpans := map[string][]time.Time{}
	for _, m := range userMessages {
		t := parseTimestamp(m.Timestamp)
		if t.IsZero() {
			continue
		}
		dt := t.In(loc)
		day := dt.Format("2006-01-02")
		dailySpans[day] = append(dailySpans[day], dt)
	}

	var workDays []WorkDay
	for day, times := range dailySpans {
		sort.Slice(times, func(i, j int) bool { return times[i].Before(times[j]) })
		spanHrs := times[len(times)-1].Sub(times[0]).Hours()
		activeSecs := 120.0
		for i := 1; i < len(times); i++ {
			gap := times[i].Sub(times[i-1]).Seconds()
			if gap > 1800 {
				gap = 1800
			}
			activeSecs += gap
		}
		activeHrs := activeSecs / 3600

		workDays = append(workDays, WorkDay{
			Date:      day,
			First:     times[0].Format("15:04"),
			Last:      times[len(times)-1].Format("15:04"),
			SpanHrs:   math.Round(spanHrs*10) / 10,
			ActiveHrs: math.Round(activeHrs*10) / 10,
			Prompts:   len(times),
		})
	}
	sort.Slice(workDays, func(i, j int) bool { return workDays[i].Date < workDays[j].Date })

	// Prompt analysis
	catCounts := map[string]int{}
	lbCounts := map[string]int{}
	type projQual struct {
		count, totalLen, confirms, detailed int
		cats                                map[string]int
	}
	projQuality := map[string]*projQual{}
	for _, p := range prompts {
		catCounts[p.Category]++
		lbCounts[p.LengthBucket]++
		if projQuality[p.Project] == nil {
			projQuality[p.Project] = &projQual{cats: map[string]int{}}
		}
		pq := projQuality[p.Project]
		pq.count++
		pq.totalLen += p.FullLength
		if p.Category == "confirmation" || p.Category == "micro" {
			pq.confirms++
		}
		if p.FullLength > 100 {
			pq.detailed++
		}
		pq.cats[p.Category]++
	}

	// Build categories sorted by count
	type catEntry struct {
		cat   string
		count int
	}
	var catEntries []catEntry
	for c, n := range catCounts {
		catEntries = append(catEntries, catEntry{c, n})
	}
	sort.Slice(catEntries, func(i, j int) bool {
		return catEntries[i].count > catEntries[j].count
	})
	totalPrompts := len(prompts)
	maxPrompts := maxInt(totalPrompts, 1)

	categories := make([]CategoryStat, len(catEntries))
	for i, e := range catEntries {
		categories[i] = CategoryStat{
			Cat:   e.cat,
			Count: e.count,
			Pct:   math.Round(float64(e.count)/float64(maxPrompts)*1000) / 10,
		}
	}

	bucketOrder := []string{"micro (<20)", "short (20-50)", "medium (50-150)", "detailed (150-500)", "comprehensive (500+)"}
	lengthBuckets := make([]LengthBucketStat, len(bucketOrder))
	for i, b := range bucketOrder {
		lengthBuckets[i] = LengthBucketStat{
			Bucket: b,
			Count:  lbCounts[b],
			Pct:    math.Round(float64(lbCounts[b])/float64(maxPrompts)*1000) / 10,
		}
	}

	// Project quality
	var pqData []ProjectQuality
	for p, d := range projQuality {
		if d.count < 5 {
			continue
		}
		topCat := ""
		topCount := 0
		for c, n := range d.cats {
			if n > topCount {
				topCat = c
				topCount = n
			}
		}
		pqData = append(pqData, ProjectQuality{
			Project:     p,
			Count:       d.count,
			AvgLen:      d.totalLen / d.count,
			ConfirmPct:  math.Round(float64(d.confirms)/float64(d.count)*1000) / 10,
			DetailedPct: math.Round(float64(d.detailed)/float64(d.count)*1000) / 10,
			TopCat:      topCat,
		})
	}
	sort.Slice(pqData, func(i, j int) bool { return pqData[i].Count > pqData[j].Count })

	totalLengths := 0
	for _, p := range prompts {
		totalLengths += p.FullLength
	}
	avgLength := 0
	if totalPrompts > 0 {
		avgLength = totalLengths / totalPrompts
	}

	analysis := Analysis{
		TotalPrompts:   totalPrompts,
		AvgLength:      avgLength,
		Categories:     categories,
		LengthBuckets:  lengthBuckets,
		ProjectQuality: pqData,
	}

	// === Model breakdown ===
	totalOutput := 0
	totalInput := 0
	totalCacheRead := 0
	totalCacheWrite := 0
	for _, c := range modelCounts {
		totalOutput += c.output
		totalInput += c.input
		totalCacheRead += c.cacheRead
		totalCacheWrite += c.cacheWrite
	}

	// Sort models by msgs desc
	type modelEntry struct {
		raw   string
		count *modelCount
	}
	var modelEntries []modelEntry
	for raw, c := range modelCounts {
		modelEntries = append(modelEntries, modelEntry{raw, c})
	}
	sort.Slice(modelEntries, func(i, j int) bool {
		return modelEntries[i].count.msgs > modelEntries[j].count.msgs
	})

	var modelBreakdown []ModelBreakdown
	for _, e := range modelEntries {
		display := NormalizeModelName(e.raw)
		costTier := MatchModelCost(e.raw)
		cost := float64(e.count.input)/1_000_000*costTier.Input +
			float64(e.count.output)/1_000_000*costTier.Output +
			float64(e.count.cacheRead)/1_000_000*costTier.CacheRead +
			float64(e.count.cacheWrite)/1_000_000*costTier.CacheWrite
		modelBreakdown = append(modelBreakdown, ModelBreakdown{
			Model:            e.raw,
			Display:          display,
			Msgs:             e.count.msgs,
			InputTokens:      e.count.input,
			OutputTokens:     e.count.output,
			CacheReadTokens:  e.count.cacheRead,
			CacheWriteTokens: e.count.cacheWrite,
			EstimatedCost:    math.Round(cost*100) / 100,
		})
	}

	// === Cost estimation ===
	totalCost := 0.0
	for _, m := range modelBreakdown {
		totalCost += m.EstimatedCost
	}

	// === Subagent analysis ===
	subagentData := ParseSubagents(claudeDir, offset)

	// Add subagent costs
	subagentCost := 0.0
	for rawModel, tokens := range subagentData.ModelTokens {
		costTier := MatchModelCost(rawModel)
		subagentCost += float64(tokens["input"])/1_000_000*costTier.Input +
			float64(tokens["output"])/1_000_000*costTier.Output +
			float64(tokens["cache_read"])/1_000_000*costTier.CacheRead
	}
	subagentData.EstimatedCost = math.Round(subagentCost*100) / 100
	totalCost += subagentCost

	// === Git branch data ===
	var branchData []BranchData
	for br, d := range branchActivity {
		projects := make([]string, 0, len(d.projects))
		for p := range d.projects {
			projects = append(projects, p)
		}
		branchData = append(branchData, BranchData{
			Branch:   br,
			Msgs:     d.msgs,
			Sessions: len(d.sessions),
			Projects: projects,
		})
	}
	sort.Slice(branchData, func(i, j int) bool {
		return branchData[i].Msgs > branchData[j].Msgs
	})
	if len(branchData) > 20 {
		branchData = branchData[:20]
	}

	// === Context efficiency ===
	totalAllOutput := totalOutput + subagentData.TotalSubagentOutputTokens
	maxTotalOutput := maxInt(totalOutput, 1)
	maxTotalAllOutput := maxInt(totalAllOutput, 1)
	contextEfficiency := ContextEfficiency{
		ToolOutputTokens:     totalToolResultTokens,
		ConversationTokens:   totalConversationTokens,
		ToolPct:              math.Round(float64(totalToolResultTokens)/float64(maxTotalOutput)*1000) / 10,
		ConversationPct:      math.Round(float64(totalConversationTokens)/float64(maxTotalOutput)*1000) / 10,
		ThinkingBlocks:       thinkingCount,
		SubagentOutputTokens: subagentData.TotalSubagentOutputTokens,
		SubagentPct:          math.Round(float64(subagentData.TotalSubagentOutputTokens)/float64(maxTotalAllOutput)*1000) / 10,
	}

	// === Version tracking ===
	type verEntry struct {
		version string
		count   int
	}
	var verEntries []verEntry
	for v, c := range versionCounts {
		verEntries = append(verEntries, verEntry{v, c})
	}
	sort.Slice(verEntries, func(i, j int) bool {
		return verEntries[i].count > verEntries[j].count
	})
	if len(verEntries) > 10 {
		verEntries = verEntries[:10]
	}
	versionData := make([]VersionData, len(verEntries))
	for i, e := range verEntries {
		versionData[i] = VersionData{Version: e.version, Count: e.count}
	}

	// === Skill/MCP usage ===
	type skillEntry struct {
		skill string
		count int
	}
	var skillEntries []skillEntry
	for s, c := range skillUsage {
		skillEntries = append(skillEntries, skillEntry{s, c})
	}
	sort.Slice(skillEntries, func(i, j int) bool {
		return skillEntries[i].count > skillEntries[j].count
	})
	if len(skillEntries) > 15 {
		skillEntries = skillEntries[:15]
	}
	skillData := make([]SkillData, len(skillEntries))
	for i, e := range skillEntries {
		skillData[i] = SkillData{Skill: e.skill, Count: e.count}
	}

	// === Slash command usage ===
	type cmdEntry struct {
		cmd   string
		count int
	}
	var cmdEntries []cmdEntry
	for c, n := range slashCommands {
		cmdEntries = append(cmdEntries, cmdEntry{c, n})
	}
	sort.Slice(cmdEntries, func(i, j int) bool {
		return cmdEntries[i].count > cmdEntries[j].count
	})
	if len(cmdEntries) > 15 {
		cmdEntries = cmdEntries[:15]
	}
	slashCommandData := make([]SlashCommandData, len(cmdEntries))
	for i, e := range cmdEntries {
		slashCommandData[i] = SlashCommandData{Command: e.cmd, Count: e.count}
	}

	// Config
	config := ParseConfig(claudeDir)

	// Total tool calls
	totalToolCalls := 0
	for _, m := range asstMessages {
		totalToolCalls += len(m.ToolUses)
	}

	// Summary
	dateRangeStart := ""
	dateRangeEnd := ""
	if len(allDates) > 0 {
		dateRangeStart = allDates[0]
		dateRangeEnd = allDates[len(allDates)-1]
	}

	avgSessionDuration := 0.0
	if len(sessionDurations) > 0 {
		totalDur := 0.0
		for _, sd := range sessionDurations {
			totalDur += sd.DurationMin
		}
		avgSessionDuration = math.Round(totalDur/float64(len(sessionDurations))*10) / 10
	}

	tzLabel := fmt.Sprintf("UTC%+d", offset)

	summary := Summary{
		TotalSessions:         len(sessionsMeta),
		TotalUserMsgs:         len(userMessages),
		TotalAssistantMsgs:    len(asstMessages),
		TotalToolCalls:        totalToolCalls,
		TotalOutputTokens:     totalOutput,
		TotalInputTokens:      totalInput,
		TotalCacheReadTokens:  totalCacheRead,
		TotalCacheWriteTokens: totalCacheWrite,
		DateRangeStart:        dateRangeStart,
		DateRangeEnd:          dateRangeEnd,
		SinceDate:             sinceDate,
		UniqueProjects:        len(projectStats),
		UniqueTools:           len(toolCounts),
		AvgSessionDuration:    avgSessionDuration,
		TzOffset:              offset,
		TzLabel:               tzLabel,
		EstimatedCost:         math.Round(totalCost*100) / 100,
		SkippedFiles:          skippedFiles,
		SkippedLines:          skippedLines,
	}

	// Ensure slices are non-nil for JSON
	if prompts == nil {
		prompts = []Prompt{}
	}
	if modelBreakdown == nil {
		modelBreakdown = []ModelBreakdown{}
	}
	if branchData == nil {
		branchData = []BranchData{}
	}
	if versionData == nil {
		versionData = []VersionData{}
	}
	if skillData == nil {
		skillData = []SkillData{}
	}
	if slashCommandData == nil {
		slashCommandData = []SlashCommandData{}
	}
	if workDays == nil {
		workDays = []WorkDay{}
	}
	if sessionDurations == nil {
		sessionDurations = []SessionDuration{}
	}
	if dailyData == nil {
		dailyData = []DailyData{}
	}
	if projectData == nil {
		projectData = []ProjectData{}
	}
	if toolData == nil {
		toolData = []ToolData{}
	}
	if weeklyData == nil {
		weeklyData = []WeeklyData{}
	}
	if efficiencyData == nil {
		efficiencyData = []EfficiencyData{}
	}
	if pqData == nil {
		pqData = []ProjectQuality{}
	}
	if analysis.ProjectQuality == nil {
		analysis.ProjectQuality = []ProjectQuality{}
	}

	return &ParseResult{
		Dashboard: Dashboard{
			Summary:    summary,
			Daily:      dailyData,
			Heatmap:    heatmapData,
			Projects:   projectData,
			Tools:      toolData,
			Hourly:     hourlyData,
			Sessions:   sessionDurations,
			Weekly:     weeklyData,
			Efficiency: efficiencyData,
		},
		Drilldown:         drilldown,
		Analysis:          analysis,
		Prompts:           prompts,
		WorkDays:          workDays,
		Models:            modelBreakdown,
		Subagents:         subagentData,
		Branches:          branchData,
		ContextEfficiency: contextEfficiency,
		Versions:          versionData,
		Skills:            skillData,
		SlashCommands:     slashCommandData,
		PermissionModes:   permissionModes,
		Config:            config,
	}, nil
}

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

use chrono::{DateTime, FixedOffset, Local, NaiveDateTime, Datelike, Timelike};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;

// === Typed output structs ===

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParseResult {
    pub dashboard: Dashboard,
    pub drilldown: HashMap<String, HashMap<String, Vec<DrilldownEntry>>>,
    pub analysis: Analysis,
    pub prompts: Vec<Prompt>,
    pub work_days: Vec<WorkDay>,
    pub models: Vec<ModelBreakdown>,
    pub subagents: SubagentData,
    pub branches: Vec<BranchData>,
    pub context_efficiency: ContextEfficiency,
    pub versions: Vec<VersionData>,
    pub skills: Vec<SkillData>,
    pub slash_commands: Vec<SlashCommandData>,
    pub permission_modes: HashMap<String, i64>,
    pub config: Config,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Dashboard {
    pub summary: Summary,
    pub daily: Vec<DailyData>,
    pub heatmap: Vec<HeatmapCell>,
    pub projects: Vec<ProjectData>,
    pub tools: Vec<ToolData>,
    pub hourly: Vec<HourlyData>,
    pub sessions: Vec<SessionDuration>,
    pub weekly: Vec<WeeklyData>,
    pub efficiency: Vec<EfficiencyData>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Summary {
    pub total_sessions: i64,
    pub total_user_msgs: i64,
    pub total_assistant_msgs: i64,
    pub total_tool_calls: i64,
    pub total_output_tokens: i64,
    pub total_input_tokens: i64,
    pub total_cache_read_tokens: i64,
    pub total_cache_write_tokens: i64,
    pub date_range_start: String,
    pub date_range_end: String,
    pub since_date: String,
    pub unique_projects: i64,
    pub unique_tools: i64,
    pub avg_session_duration: f64,
    pub tz_offset: i32,
    pub tz_label: String,
    pub estimated_cost: f64,
    pub skipped_files: i64,
    pub skipped_lines: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DailyData {
    pub date: String,
    pub user_msgs: i64,
    pub assistant_msgs: i64,
    pub tool_calls: i64,
    pub output_tokens: i64,
    pub total_msgs: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HeatmapCell {
    pub weekday: i64,
    pub hour: i64,
    pub count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectData {
    pub project: String,
    pub user_msgs: i64,
    pub assistant_msgs: i64,
    pub tool_calls: i64,
    pub sessions: i64,
    pub output_tokens: i64,
    pub total_msgs: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolData {
    pub tool: String,
    pub count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HourlyData {
    pub hour: i64,
    pub count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionDuration {
    pub session_id: String,
    pub project: String,
    pub duration_min: f64,
    pub user_msgs: i64,
    pub assistant_msgs: i64,
    pub tool_uses: i64,
    pub date: String,
    pub start_hour: u32,
    pub msgs_per_min: f64,
    pub git_branch: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WeeklyData {
    pub week: String,
    pub user_msgs: i64,
    pub sessions: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EfficiencyData {
    pub hour: u32,
    pub avg_msgs_per_session: f64,
    pub avg_duration: f64,
    pub sessions: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkDay {
    pub date: String,
    pub first: String,
    pub last: String,
    pub span_hrs: f64,
    pub active_hrs: f64,
    pub prompts: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Prompt {
    pub text: String,
    pub full_length: i64,
    pub project: String,
    pub session_id: String,
    pub date: String,
    pub time: String,
    pub hour: i64,
    pub weekday: i64,
    pub category: String,
    pub length_bucket: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DrilldownEntry {
    pub time: String,
    pub text: String,
    pub category: String,
    pub length: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Analysis {
    pub total_prompts: i64,
    pub avg_length: i64,
    pub categories: Vec<CategoryStat>,
    pub length_buckets: Vec<LengthBucketStat>,
    pub project_quality: Vec<ProjectQuality>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CategoryStat {
    pub cat: String,
    pub count: i64,
    pub pct: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LengthBucketStat {
    pub bucket: String,
    pub count: i64,
    pub pct: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectQuality {
    pub project: String,
    pub count: i64,
    pub avg_len: i64,
    pub confirm_pct: f64,
    pub detailed_pct: f64,
    pub top_cat: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelBreakdown {
    pub model: String,
    pub display: String,
    pub msgs: i64,
    pub input_tokens: i64,
    pub output_tokens: i64,
    pub cache_read_tokens: i64,
    pub cache_write_tokens: i64,
    pub estimated_cost: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubagentEntry {
    pub agent_id: String,
    #[serde(rename = "type")]
    pub agent_type: String,
    pub description: String,
    pub is_compaction: bool,
    pub project: String,
    pub messages: i64,
    pub tool_calls: i64,
    pub input_tokens: i64,
    pub output_tokens: i64,
    pub cache_read_tokens: i64,
    pub models: Vec<String>,
    pub duration_min: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubagentData {
    pub subagents: Vec<SubagentEntry>,
    pub type_counts: HashMap<String, i64>,
    pub total_count: i64,
    pub compaction_count: i64,
    pub total_subagent_input_tokens: i64,
    pub total_subagent_output_tokens: i64,
    pub model_tokens: HashMap<String, SubagentModelTokens>,
    pub estimated_cost: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubagentModelTokens {
    pub input: i64,
    pub output: i64,
    pub cache_read: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BranchData {
    pub branch: String,
    pub msgs: i64,
    pub sessions: i64,
    pub projects: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextEfficiency {
    pub tool_output_tokens: i64,
    pub conversation_tokens: i64,
    pub tool_pct: f64,
    pub conversation_pct: f64,
    pub thinking_blocks: i64,
    pub subagent_output_tokens: i64,
    pub subagent_pct: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VersionData {
    pub version: String,
    pub count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillData {
    pub skill: String,
    pub count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SlashCommandData {
    pub command: String,
    pub count: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FeatureFlag {
    pub name: String,
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VersionInfo {
    pub migration_version: String,
    pub first_start: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Config {
    pub has_config: bool,
    pub plugins: Vec<String>,
    pub feature_flags: Vec<FeatureFlag>,
    pub version_info: VersionInfo,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Recommendation {
    pub title: String,
    pub severity: String,
    pub body: String,
    pub metric: String,
    pub example: String,
    #[serde(default)]
    pub rec_source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecommendationsResult {
    pub recommendations: Vec<Recommendation>,
    pub source: String,
}

// === COST ESTIMATES (per million tokens, USD) ===
pub struct ModelCost {
    pub input: f64,
    pub output: f64,
    pub cache_read: f64,
    pub cache_write: f64,
}

/// Truncate a string to at most `max` bytes, ensuring we don't split a multi-byte char.
fn truncate(s: &str, max: usize) -> &str {
    if s.len() <= max { return s; }
    let mut end = max;
    while end > 0 && !s.is_char_boundary(end) { end -= 1; }
    &s[..end]
}

pub fn match_model_cost(model_str: &str) -> ModelCost {
    let m = model_str.to_lowercase();
    if m.contains("opus") {
        return ModelCost { input: 15.0, output: 75.0, cache_read: 1.5, cache_write: 18.75 };
    }
    if m.contains("sonnet") {
        return ModelCost { input: 3.0, output: 15.0, cache_read: 0.30, cache_write: 3.75 };
    }
    if m.contains("haiku") {
        return ModelCost { input: 0.80, output: 4.0, cache_read: 0.08, cache_write: 1.0 };
    }
    // Default to sonnet
    ModelCost { input: 3.0, output: 15.0, cache_read: 0.30, cache_write: 3.75 }
}

pub fn detect_timezone_offset() -> i32 {
    let local_offset = Local::now().offset().local_minus_utc();
    (local_offset as f64 / 3600.0).round() as i32
}

pub fn find_claude_dir() -> Result<PathBuf, String> {
    let home = dirs_home();
    let claude_dir = home.join(".claude");
    if !claude_dir.exists() {
        return Err(format!(
            "Claude directory not found at {}\nMake sure you have Claude Code installed and have used it at least once.",
            claude_dir.display()
        ));
    }
    Ok(claude_dir)
}

fn dirs_home() -> PathBuf {
    std::env::var("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("/"))
}

pub fn find_session_files(claude_dir: &Path) -> Result<Vec<PathBuf>, String> {
    let projects_dir = claude_dir.join("projects");
    if !projects_dir.exists() {
        return Err(format!("No projects directory found at {}", projects_dir.display()));
    }

    let pattern = format!("{}/*/*.jsonl", projects_dir.display());
    let mut main_sessions: Vec<PathBuf> = glob::glob(&pattern)
        .map_err(|e| format!("Glob error: {}", e))?
        .filter_map(|r| r.ok())
        .filter(|p| !p.to_string_lossy().contains("subagent"))
        .collect();
    main_sessions.sort();
    Ok(main_sessions)
}

fn find_subagent_files(claude_dir: &Path) -> (Vec<PathBuf>, Vec<PathBuf>) {
    let projects_dir = claude_dir.join("projects");
    if !projects_dir.exists() {
        return (vec![], vec![]);
    }

    let jsonl_pattern = format!("{}/*/*/subagents/*.jsonl", projects_dir.display());
    let meta_pattern = format!("{}/*/*/subagents/*.meta.json", projects_dir.display());

    let jsonl_files: Vec<PathBuf> = glob::glob(&jsonl_pattern)
        .map(|g| g.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();
    let meta_files: Vec<PathBuf> = glob::glob(&meta_pattern)
        .map(|g| g.filter_map(|r| r.ok()).collect())
        .unwrap_or_default();

    (jsonl_files, meta_files)
}

pub fn clean_project_name(dirname: &str) -> String {
    let home_str = dirs_home().to_string_lossy().replace('/', "-").replace('\\', "-");
    let home_trimmed = if home_str.starts_with('-') { &home_str[1..] } else { &home_str };

    let mut name = dirname.to_string();
    let with_dash = format!("{}-", home_trimmed);
    name = name.replace(&with_dash, "");
    name = name.replace(home_trimmed, "home");
    if name.starts_with('-') {
        name = name[1..].to_string();
    }
    if name.is_empty() {
        "unknown".to_string()
    } else {
        name
    }
}

pub fn normalize_model_name(model_str: &str) -> String {
    if model_str.is_empty() {
        return "unknown".to_string();
    }
    let m = model_str.to_lowercase();
    if m.contains("opus") {
        return "Opus".to_string();
    }
    if m.contains("sonnet") {
        return "Sonnet".to_string();
    }
    if m.contains("haiku") {
        return "Haiku".to_string();
    }
    model_str.to_string()
}

fn has_word(words: &[&str], text: &str) -> bool {
    for w in words {
        let pattern = format!(r"\b{}\b", regex::escape(w));
        if let Ok(re) = Regex::new(&pattern) {
            if re.is_match(text) {
                return true;
            }
        }
    }
    false
}

pub fn categorize_prompt(text: &str) -> String {
    let t = text.to_lowercase();
    let t = t.trim();
    if t.len() < 5 {
        return "micro".to_string();
    }

    let confirm_re = Regex::new(
        r"^(y(es)?|yeah|yep|ok(ay)?|sure|go|do it|proceed|looks good|lgtm|correct|right|confirm|approved|continue|k|yea|np|go ahead|ship it|perfect|great|nice|good|cool|thanks|ty|thx)\s*$"
    ).unwrap();
    if confirm_re.is_match(t) {
        return "confirmation".to_string();
    }

    if has_word(&["error", "bug", "fix", "broken", "crash", "fail", "issue",
                   "wrong", "not working", "doesn't work", "won't", "undefined",
                   "null", "exception", "traceback"], t) {
        return "debugging".to_string();
    }

    if has_word(&["add", "create", "build", "implement", "make", "new feature",
                   "set up", "setup", "write", "generate"], t) {
        return "building".to_string();
    }

    if has_word(&["refactor", "clean up", "rename", "move", "restructure",
                   "reorganize", "simplify", "extract"], t) {
        return "refactoring".to_string();
    }

    let question_starts = ["how", "what", "why", "where", "when", "can you", "is there",
                            "do we", "does", "which", "should"];
    if question_starts.iter().any(|s| t.starts_with(s)) {
        return "question".to_string();
    }

    if has_word(&["review", "check", "look at", "examine", "inspect", "analyze",
                   "show me", "read", "list", "find"], t) {
        return "review".to_string();
    }

    if has_word(&["update", "change", "modify", "edit", "replace", "remove",
                   "delete", "tweak", "adjust"], t) {
        return "editing".to_string();
    }

    if has_word(&["test", "spec", "coverage", "assert", "expect"], t) {
        return "testing".to_string();
    }

    if has_word(&["commit", "push", "deploy", "merge", "branch", "pr ",
                   "pull request", "git "], t) {
        return "git_ops".to_string();
    }

    if t.len() < 30 {
        return "brief".to_string();
    }

    "detailed".to_string()
}

pub fn length_bucket(length: usize) -> String {
    if length < 20 {
        "micro (<20)".to_string()
    } else if length < 50 {
        "short (20-50)".to_string()
    } else if length < 150 {
        "medium (50-150)".to_string()
    } else if length < 500 {
        "detailed (150-500)".to_string()
    } else {
        "comprehensive (500+)".to_string()
    }
}

pub fn parse_config(claude_dir: &Path) -> Config {
    let config_path = claude_dir.join(".claude.json");
    let mut config = Config {
        has_config: false,
        plugins: vec![],
        feature_flags: vec![],
        version_info: VersionInfo {
            migration_version: String::new(),
            first_start: String::new(),
        },
    };

    if !config_path.exists() {
        return config;
    }

    if let Ok(contents) = fs::read_to_string(&config_path) {
        if let Ok(data) = serde_json::from_str::<Value>(&contents) {
            config.has_config = true;

            // Extract plugins
            if let Some(features) = data.get("cachedGrowthBookFeatures").and_then(|v| v.as_object()) {
                if let Some(amber_lattice) = features.get("tengu_amber_lattice").and_then(|v| v.as_object()) {
                    if let Some(plugins) = amber_lattice.get("value").and_then(|v| v.as_array()) {
                        config.plugins = plugins.iter()
                            .filter_map(|p| p.as_str().map(|s| s.to_string()))
                            .collect();
                    }
                }

                // Extract feature flags
                for (key, val) in features {
                    let clean_name = key.replace("tengu_", "");
                    if let Some(obj) = val.as_object() {
                        let enabled = obj.get("value").map(|v| v.as_bool().unwrap_or(false)).unwrap_or(false);
                        config.feature_flags.push(FeatureFlag {
                            name: clean_name,
                            enabled,
                        });
                    } else if let Some(b) = val.as_bool() {
                        config.feature_flags.push(FeatureFlag {
                            name: clean_name,
                            enabled: b,
                        });
                    }
                }
            }

            // Migration / account info
            config.version_info = VersionInfo {
                migration_version: data.get("migrationVersion").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                first_start: data.get("firstStartTime").and_then(|v| v.as_str()).unwrap_or("").to_string(),
            };
        }
    }

    config
}

fn parse_timestamp(ts: &str) -> Option<DateTime<FixedOffset>> {
    let cleaned = ts.replace("Z", "+00:00");
    DateTime::parse_from_rfc3339(&cleaned).ok()
        .or_else(|| {
            // Try parsing without timezone
            NaiveDateTime::parse_from_str(ts, "%Y-%m-%dT%H:%M:%S%.f")
                .ok()
                .and_then(|ndt| {
                    let offset = FixedOffset::east_opt(0)?;
                    ndt.and_local_timezone(offset).single()
                })
        })
}

fn apply_tz_offset(dt: &DateTime<FixedOffset>, tz_offset: i32) -> DateTime<FixedOffset> {
    let offset = FixedOffset::east_opt(tz_offset * 3600).unwrap();
    dt.with_timezone(&offset)
}

pub fn parse_subagents(claude_dir: &Path, _tz_offset: i32) -> SubagentData {
    let (jsonl_files, meta_files) = find_subagent_files(claude_dir);

    // Build meta lookup
    let mut meta_lookup: HashMap<String, (String, String)> = HashMap::new();
    for mf in &meta_files {
        if let Ok(contents) = fs::read_to_string(mf) {
            if let Ok(meta) = serde_json::from_str::<Value>(&contents) {
                let stem = mf.file_stem().unwrap_or_default().to_string_lossy().to_string();
                let agent_id = stem.replace("agent-", "").replace(".meta", "");
                let agent_type = meta.get("agentType").and_then(|v| v.as_str()).unwrap_or("unknown").to_string();
                let description = meta.get("description").and_then(|v| v.as_str()).unwrap_or("").to_string();
                meta_lookup.insert(agent_id, (agent_type, description));
            }
        }
    }

    let mut subagents: Vec<SubagentEntry> = Vec::new();
    let mut type_counts: HashMap<String, i64> = HashMap::new();
    let mut model_tokens: HashMap<String, (i64, i64, i64)> = HashMap::new(); // input, output, cache_read

    for filepath in &jsonl_files {
        let stem = filepath.file_stem().unwrap_or_default().to_string_lossy().to_string();
        let agent_id = stem.replace("agent-", "");
        let is_compaction = agent_id.to_lowercase().contains("compact");

        let (agent_type, description) = meta_lookup
            .get(&agent_id)
            .cloned()
            .unwrap_or_else(|| ("unknown".to_string(), String::new()));

        *type_counts.entry(agent_type.clone()).or_insert(0) += 1;

        let mut msg_count: i64 = 0;
        let mut tool_calls: i64 = 0;
        let mut input_tokens: i64 = 0;
        let mut output_tokens: i64 = 0;
        let mut cache_read: i64 = 0;
        let mut models_used: HashSet<String> = HashSet::new();
        let mut first_ts: Option<String> = None;
        let mut last_ts: Option<String> = None;

        if let Ok(contents) = fs::read_to_string(filepath) {
            for line in contents.lines() {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }
                let d: Value = match serde_json::from_str(line) {
                    Ok(v) => v,
                    Err(_) => continue,
                };

                if let Some(ts) = d.get("timestamp").and_then(|v| v.as_str()) {
                    let ts_str = ts.to_string();
                    if first_ts.is_none() || ts_str < *first_ts.as_ref().unwrap() {
                        first_ts = Some(ts_str.clone());
                    }
                    if last_ts.is_none() || ts_str > *last_ts.as_ref().unwrap() {
                        last_ts = Some(ts_str);
                    }
                }

                if let Some(msg) = d.get("message").and_then(|v| v.as_object()) {
                    if let Some(m) = msg.get("model").and_then(|v| v.as_str()) {
                        if !m.is_empty() {
                            models_used.insert(m.to_string());
                        }
                    }
                    if let Some(usage) = msg.get("usage").and_then(|v| v.as_object()) {
                        input_tokens += usage.get("input_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
                        output_tokens += usage.get("output_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
                        cache_read += usage.get("cache_read_input_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
                    }
                    if let Some(content) = msg.get("content").and_then(|v| v.as_array()) {
                        for c in content {
                            if c.get("type").and_then(|v| v.as_str()) == Some("tool_use") {
                                tool_calls += 1;
                            }
                        }
                    }
                }

                msg_count += 1;
            }
        }

        // Get parent project
        let proj_name = filepath
            .parent() // subagents/
            .and_then(|p| p.parent()) // session_id/
            .and_then(|p| p.parent()) // project_dir/
            .and_then(|p| p.file_name())
            .map(|n| clean_project_name(&n.to_string_lossy()))
            .unwrap_or_else(|| "unknown".to_string());

        let mut duration: f64 = 0.0;
        if let (Some(ref fts), Some(ref lts)) = (&first_ts, &last_ts) {
            if let (Some(t1), Some(t2)) = (parse_timestamp(fts), parse_timestamp(lts)) {
                duration = (t2 - t1).num_seconds() as f64 / 60.0;
            }
        }

        let agent_id_short = truncate(&agent_id, 12).to_string();
        let desc_short = truncate(&description, 80).to_string();

        let models_vec: Vec<String> = models_used.iter().cloned().collect();

        subagents.push(SubagentEntry {
            agent_id: agent_id_short,
            agent_type: agent_type.clone(),
            description: desc_short,
            is_compaction,
            project: proj_name,
            messages: msg_count,
            tool_calls,
            input_tokens,
            output_tokens,
            cache_read_tokens: cache_read,
            models: models_vec,
            duration_min: (duration * 10.0).round() / 10.0,
        });

        // Accumulate tokens by model for subagents
        let num_models = models_used.len().max(1) as i64;
        for m in &models_used {
            let entry = model_tokens.entry(m.clone()).or_insert((0, 0, 0));
            entry.0 += input_tokens / num_models;
            entry.1 += output_tokens / num_models;
            entry.2 += cache_read / num_models;
        }
    }

    let model_tokens_map: HashMap<String, SubagentModelTokens> = model_tokens.iter()
        .map(|(model, (inp, out, cr))| {
            (model.clone(), SubagentModelTokens {
                input: *inp,
                output: *out,
                cache_read: *cr,
            })
        })
        .collect();

    let compaction_count = subagents.iter().filter(|s| s.is_compaction).count() as i64;
    let total_input: i64 = subagents.iter().map(|s| s.input_tokens).sum();
    let total_output: i64 = subagents.iter().map(|s| s.output_tokens).sum();

    SubagentData {
        total_count: subagents.len() as i64,
        compaction_count,
        total_subagent_input_tokens: total_input,
        total_subagent_output_tokens: total_output,
        model_tokens: model_tokens_map,
        estimated_cost: 0.0, // Will be computed by caller
        subagents,
        type_counts,
    }
}

// Internal message struct used during parsing (not serialized to output)
#[allow(dead_code)]
struct MsgRecord {
    timestamp: String,
    date: String,
    hour: i64,
    weekday: i64,
    msg_type: String, // "user" or "assistant"
    project: String,
    session_id: String,
    tool_uses: Vec<String>,
    input_tokens: i64,
    output_tokens: i64,
    model: String,
}

#[allow(dead_code)]
struct SessionMeta {
    project: String,
    session_id: String,
    first_ts: String,
    last_ts: String,
    user_msgs: i64,
    assistant_msgs: i64,
    tool_uses: i64,
    model: String,
    git_branch: Option<String>,
    input_tokens: i64,
    output_tokens: i64,
    cache_read_tokens: i64,
    cache_write_tokens: i64,
}

pub fn parse_all_sessions(claude_dir: &Path, tz_offset: Option<i32>, since_date: Option<&str>) -> Result<ParseResult, String> {
    let tz_offset = tz_offset.unwrap_or_else(detect_timezone_offset);
    let session_files = find_session_files(claude_dir)?;

    if session_files.is_empty() {
        return Err("No session files found. Use Claude Code for a while first!".to_string());
    }

    // === Pass 1: Extract all messages ===
    let mut all_messages: Vec<MsgRecord> = Vec::new();
    let mut sessions_meta: Vec<SessionMeta> = Vec::new();
    let mut prompts: Vec<Prompt> = Vec::new();
    // drilldown: date -> project -> list of entries
    let mut drilldown: HashMap<String, HashMap<String, Vec<DrilldownEntry>>> = HashMap::new();

    // Model tracking
    struct ModelAccum {
        msgs: i64,
        input: i64,
        output: i64,
        cache_read: i64,
        cache_write: i64,
    }
    let mut model_counts: HashMap<String, ModelAccum> = HashMap::new();
    let mut branch_activity: HashMap<String, (i64, HashSet<String>, HashSet<String>)> = HashMap::new();
    let mut version_counts: HashMap<String, i64> = HashMap::new();
    let mut thinking_count: i64 = 0;
    let mut total_tool_result_tokens: i64 = 0;
    let mut total_conversation_tokens: i64 = 0;
    let mut skipped_files: i64 = 0;
    let mut skipped_lines: i64 = 0;
    let mut skill_usage: HashMap<String, i64> = HashMap::new();
    let mut slash_commands: HashMap<String, i64> = HashMap::new();
    let mut permission_modes: HashMap<String, i64> = HashMap::new();

    let weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

    for filepath in &session_files {
        let project_dir = filepath.parent()
            .and_then(|p| p.file_name())
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| "unknown".to_string());
        let proj_name = clean_project_name(&project_dir);
        let session_id = filepath.file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_default();
        let session_id_short = truncate(&session_id, 8).to_string();

        let mut timestamps: Vec<String> = Vec::new();
        let mut user_msgs: i64 = 0;
        let mut assistant_msgs: i64 = 0;
        let mut tool_uses: i64 = 0;
        let mut model: String = String::new();
        let mut git_branch: Option<String> = None;
        let mut session_input_tokens: i64 = 0;
        let mut session_output_tokens: i64 = 0;
        let mut session_cache_read: i64 = 0;
        let mut session_cache_write: i64 = 0;

        let contents = match fs::read_to_string(filepath) {
            Ok(c) => c,
            Err(_) => { skipped_files += 1; continue; },
        };

        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let d: Value = match serde_json::from_str(line) {
                Ok(v) => v,
                Err(_) => { skipped_lines += 1; continue; },
            };

            let msg_type = d.get("type").and_then(|v| v.as_str()).unwrap_or("");
            let ts = d.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");

            // Track version, branch, permission mode
            if let Some(ver) = d.get("version").and_then(|v| v.as_str()) {
                *version_counts.entry(ver.to_string()).or_insert(0) += 1;
            }
            if let Some(br) = d.get("gitBranch").and_then(|v| v.as_str()) {
                if br != "HEAD" {
                    git_branch = Some(br.to_string());
                }
            }
            if let Some(pm) = d.get("permissionMode").and_then(|v| v.as_str()) {
                *permission_modes.entry(pm.to_string()).or_insert(0) += 1;
            }

            if msg_type == "user" && !ts.is_empty() {
                let parsed_dt = match parse_timestamp(ts) {
                    Some(dt) => dt,
                    None => continue,
                };
                let dt = apply_tz_offset(&parsed_dt, tz_offset);

                // Skip messages before the since_date cutoff
                let date_str = dt.format("%Y-%m-%d").to_string();
                if let Some(since) = since_date {
                    if date_str.as_str() < since {
                        continue;
                    }
                }

                user_msgs += 1;

                let hour = dt.hour() as i64;
                let weekday = dt.weekday().num_days_from_monday() as i64;
                let _weekday_name = weekday_names[weekday as usize];
                let time_str = dt.format("%H:%M").to_string();
                let _month_str = dt.format("%Y-%m").to_string();

                all_messages.push(MsgRecord {
                    timestamp: ts.to_string(),
                    date: date_str.clone(),
                    hour,
                    weekday,
                    msg_type: "user".to_string(),
                    project: proj_name.clone(),
                    session_id: session_id_short.clone(),
                    tool_uses: vec![],
                    input_tokens: 0,
                    output_tokens: 0,
                    model: String::new(),
                });
                timestamps.push(ts.to_string());

                // Extract prompt text
                let msg = d.get("message");
                let mut text = String::new();
                let mut is_tool_result = false;

                if let Some(msg_obj) = msg.and_then(|v| v.as_object()) {
                    if let Some(content) = msg_obj.get("content") {
                        if let Some(s) = content.as_str() {
                            text = s.trim().to_string();
                        } else if let Some(arr) = content.as_array() {
                            let mut has_text = false;
                            for c in arr {
                                if let Some(obj) = c.as_object() {
                                    let ctype = obj.get("type").and_then(|v| v.as_str()).unwrap_or("");
                                    if ctype == "text" {
                                        if let Some(t) = obj.get("text").and_then(|v| v.as_str()) {
                                            if !t.trim().is_empty() {
                                                text.push_str(t);
                                                text.push(' ');
                                                has_text = true;
                                            }
                                        }
                                    } else if ctype == "tool_result" {
                                        is_tool_result = true;
                                    }
                                }
                            }
                            text = text.trim().to_string();
                            if !has_text && is_tool_result {
                                text.clear();
                            }
                        }
                    }
                }

                if !text.is_empty() {
                    let full_length = text.len() as i64;
                    let text_short = truncate(&text, 500).to_string();
                    let category = categorize_prompt(&text);
                    let lb = length_bucket(text.len());

                    prompts.push(Prompt {
                        text: text_short,
                        full_length,
                        project: proj_name.clone(),
                        session_id: session_id_short.clone(),
                        date: date_str.clone(),
                        time: time_str.clone(),
                        hour,
                        weekday,
                        category: category.clone(),
                        length_bucket: lb,
                    });

                    let text_drilldown = truncate(&text, 200).to_string();
                    drilldown
                        .entry(date_str.clone())
                        .or_default()
                        .entry(proj_name.clone())
                        .or_default()
                        .push(DrilldownEntry {
                            time: time_str.clone(),
                            text: text_drilldown,
                            category,
                            length: full_length,
                        });
                }

                // Track branch activity
                if let Some(ref br) = git_branch {
                    let entry = branch_activity.entry(br.clone()).or_insert_with(|| (0, HashSet::new(), HashSet::new()));
                    entry.0 += 1;
                    entry.1.insert(session_id_short.clone());
                    entry.2.insert(proj_name.clone());
                }

            } else if msg_type == "assistant" && !ts.is_empty() {
                let parsed_dt = match parse_timestamp(ts) {
                    Some(dt) => dt,
                    None => continue,
                };
                let dt = apply_tz_offset(&parsed_dt, tz_offset);

                let date_str = dt.format("%Y-%m-%d").to_string();
                if let Some(since) = since_date {
                    if date_str.as_str() < since {
                        continue;
                    }
                }

                assistant_msgs += 1;
                timestamps.push(ts.to_string());

                let msg = d.get("message");
                let mut msg_model = String::new();
                let mut msg_tools: Vec<String> = Vec::new();
                let mut input_tokens: i64 = 0;
                let mut output_tokens: i64 = 0;
                let mut cache_read_tokens: i64 = 0;
                let mut cache_write_tokens: i64 = 0;

                if let Some(msg_obj) = msg.and_then(|v| v.as_object()) {
                    if let Some(m) = msg_obj.get("model").and_then(|v| v.as_str()) {
                        msg_model = m.to_string();
                        if !msg_model.is_empty() {
                            model = msg_model.clone();
                        }
                    }
                    if let Some(content) = msg_obj.get("content").and_then(|v| v.as_array()) {
                        for c in content {
                            if let Some(obj) = c.as_object() {
                                let ctype = obj.get("type").and_then(|v| v.as_str()).unwrap_or("");
                                if ctype == "tool_use" {
                                    let tool_name = obj.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
                                    // Track MCP tool usage
                                    if tool_name.starts_with("mcp__") {
                                        let parts: Vec<&str> = tool_name.split("__").collect();
                                        if parts.len() > 1 {
                                            *skill_usage.entry(parts[1].to_string()).or_insert(0) += 1;
                                        }
                                    }
                                    // Track slash command / skill invocations
                                    if tool_name == "Skill" {
                                        let skill_name = obj.get("input")
                                            .and_then(|v| v.get("skill"))
                                            .and_then(|v| v.as_str())
                                            .unwrap_or("unknown")
                                            .to_string();
                                        if !skill_name.is_empty() {
                                            *slash_commands.entry(skill_name).or_insert(0) += 1;
                                        }
                                    }
                                    msg_tools.push(tool_name);
                                } else if ctype == "thinking" {
                                    thinking_count += 1;
                                }
                            }
                        }
                        tool_uses += msg_tools.len() as i64;
                    }
                    if let Some(usage) = msg_obj.get("usage").and_then(|v| v.as_object()) {
                        input_tokens = usage.get("input_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
                        output_tokens = usage.get("output_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
                        cache_read_tokens = usage.get("cache_read_input_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
                        cache_write_tokens = usage.get("cache_creation_input_tokens").and_then(|v| v.as_i64()).unwrap_or(0);
                    }
                }

                // Accumulate session tokens
                session_input_tokens += input_tokens;
                session_output_tokens += output_tokens;
                session_cache_read += cache_read_tokens;
                session_cache_write += cache_write_tokens;

                // Track per-model token usage
                let norm_model = if !msg_model.is_empty() { msg_model.clone() } else if !model.is_empty() { model.clone() } else { "unknown".to_string() };
                let mc = model_counts.entry(norm_model).or_insert(ModelAccum { msgs: 0, input: 0, output: 0, cache_read: 0, cache_write: 0 });
                mc.msgs += 1;
                mc.input += input_tokens;
                mc.output += output_tokens;
                mc.cache_read += cache_read_tokens;
                mc.cache_write += cache_write_tokens;

                // Track tool result vs conversation tokens
                if !msg_tools.is_empty() {
                    total_tool_result_tokens += output_tokens;
                } else {
                    total_conversation_tokens += output_tokens;
                }

                // Track branch activity for assistant msgs too
                if let Some(ref br) = git_branch {
                    let entry = branch_activity.entry(br.clone()).or_insert_with(|| (0, HashSet::new(), HashSet::new()));
                    entry.0 += 1;
                }

                all_messages.push(MsgRecord {
                    timestamp: ts.to_string(),
                    date: date_str,
                    hour: dt.hour() as i64,
                    weekday: dt.weekday().num_days_from_monday() as i64,
                    msg_type: "assistant".to_string(),
                    project: proj_name.clone(),
                    session_id: session_id_short.clone(),
                    tool_uses: msg_tools,
                    input_tokens,
                    output_tokens,
                    model: msg_model,
                });
            }
        }

        if !timestamps.is_empty() {
            timestamps.sort();
            sessions_meta.push(SessionMeta {
                project: proj_name,
                session_id: session_id_short,
                first_ts: timestamps.first().unwrap().clone(),
                last_ts: timestamps.last().unwrap().clone(),
                user_msgs,
                assistant_msgs,
                tool_uses,
                model,
                git_branch,
                input_tokens: session_input_tokens,
                output_tokens: session_output_tokens,
                cache_read_tokens: session_cache_read,
                cache_write_tokens: session_cache_write,
            });
        }
    }

    // === Pass 2: Aggregate ===
    let user_messages: Vec<&MsgRecord> = all_messages.iter().filter(|m| m.msg_type == "user").collect();
    let asst_messages: Vec<&MsgRecord> = all_messages.iter().filter(|m| m.msg_type == "assistant").collect();

    // Daily data
    let mut daily_user: HashMap<String, i64> = HashMap::new();
    let mut daily_asst: HashMap<String, i64> = HashMap::new();
    let mut daily_tools: HashMap<String, i64> = HashMap::new();
    let mut daily_tokens: HashMap<String, i64> = HashMap::new();

    for m in &user_messages {
        *daily_user.entry(m.date.clone()).or_insert(0) += 1;
    }
    for m in &asst_messages {
        *daily_asst.entry(m.date.clone()).or_insert(0) += 1;
        *daily_tools.entry(m.date.clone()).or_insert(0) += m.tool_uses.len() as i64;
        *daily_tokens.entry(m.date.clone()).or_insert(0) += m.output_tokens;
    }

    let mut all_dates: Vec<String> = {
        let mut s: HashSet<String> = HashSet::new();
        for k in daily_user.keys() { s.insert(k.clone()); }
        for k in daily_asst.keys() { s.insert(k.clone()); }
        s.into_iter().collect()
    };
    all_dates.sort();

    let daily_data: Vec<DailyData> = all_dates.iter().map(|d| {
        let u = daily_user.get(d).copied().unwrap_or(0);
        let a = daily_asst.get(d).copied().unwrap_or(0);
        DailyData {
            date: d.clone(),
            user_msgs: u,
            assistant_msgs: a,
            tool_calls: daily_tools.get(d).copied().unwrap_or(0),
            output_tokens: daily_tokens.get(d).copied().unwrap_or(0),
            total_msgs: u + a,
        }
    }).collect();

    // Heatmap
    let mut heatmap_counts: HashMap<String, i64> = HashMap::new();
    for m in &user_messages {
        *heatmap_counts.entry(format!("{}_{}", m.weekday, m.hour)).or_insert(0) += 1;
    }
    let mut heatmap_data: Vec<HeatmapCell> = Vec::new();
    for wd in 0..7 {
        for hr in 0..24 {
            heatmap_data.push(HeatmapCell {
                weekday: wd,
                hour: hr,
                count: heatmap_counts.get(&format!("{}_{}", wd, hr)).copied().unwrap_or(0),
            });
        }
    }

    // Project stats
    struct ProjStats {
        user_msgs: i64,
        assistant_msgs: i64,
        tool_calls: i64,
        sessions: HashSet<String>,
        output_tokens: i64,
    }
    let mut project_stats: HashMap<String, ProjStats> = HashMap::new();
    for m in &all_messages {
        let ps = project_stats.entry(m.project.clone()).or_insert(ProjStats {
            user_msgs: 0, assistant_msgs: 0, tool_calls: 0, sessions: HashSet::new(), output_tokens: 0,
        });
        ps.sessions.insert(m.session_id.clone());
        if m.msg_type == "user" {
            ps.user_msgs += 1;
        } else {
            ps.assistant_msgs += 1;
            ps.tool_calls += m.tool_uses.len() as i64;
            ps.output_tokens += m.output_tokens;
        }
    }

    let mut project_data: Vec<ProjectData> = project_stats.iter().map(|(p, s)| {
        ProjectData {
            project: p.clone(),
            user_msgs: s.user_msgs,
            assistant_msgs: s.assistant_msgs,
            tool_calls: s.tool_calls,
            sessions: s.sessions.len() as i64,
            output_tokens: s.output_tokens,
            total_msgs: s.user_msgs + s.assistant_msgs,
        }
    }).collect();
    project_data.sort_by(|a, b| b.total_msgs.cmp(&a.total_msgs));

    // Tool stats
    let mut tool_counts: HashMap<String, i64> = HashMap::new();
    for m in &asst_messages {
        for t in &m.tool_uses {
            *tool_counts.entry(t.clone()).or_insert(0) += 1;
        }
    }
    let mut tool_data_vec: Vec<(String, i64)> = tool_counts.into_iter().collect();
    tool_data_vec.sort_by(|a, b| b.1.cmp(&a.1));
    tool_data_vec.truncate(20);
    let tool_data: Vec<ToolData> = tool_data_vec.into_iter()
        .map(|(t, c)| ToolData { tool: t, count: c })
        .collect();

    // Hourly
    let mut hourly_counts: HashMap<i64, i64> = HashMap::new();
    for m in &user_messages {
        *hourly_counts.entry(m.hour).or_insert(0) += 1;
    }
    let hourly_data: Vec<HourlyData> = (0..24).map(|h| {
        HourlyData { hour: h, count: hourly_counts.get(&h).copied().unwrap_or(0) }
    }).collect();

    // Session durations
    let mut session_durations: Vec<SessionDuration> = Vec::new();
    for s in &sessions_meta {
        if let (Some(t1), Some(t2)) = (parse_timestamp(&s.first_ts), parse_timestamp(&s.last_ts)) {
            let dur = (t2 - t1).num_seconds() as f64 / 60.0;
            let t1_local = apply_tz_offset(&t1, tz_offset);
            let msg_count = s.user_msgs + s.assistant_msgs;
            let msgs_per_min = if dur > 0.0 { (msg_count as f64 / dur * 100.0).round() / 100.0 } else { 0.0 };
            session_durations.push(SessionDuration {
                session_id: s.session_id.clone(),
                project: s.project.clone(),
                duration_min: (dur * 10.0).round() / 10.0,
                user_msgs: s.user_msgs,
                assistant_msgs: s.assistant_msgs,
                tool_uses: s.tool_uses,
                date: t1_local.format("%Y-%m-%d").to_string(),
                start_hour: t1_local.hour(),
                msgs_per_min,
                git_branch: s.git_branch.clone(),
            });
        }
    }

    // Weekly
    let mut weekly_agg: HashMap<String, (i64, HashSet<String>)> = HashMap::new();
    for m in &user_messages {
        if let Some(dt) = parse_timestamp(&m.timestamp) {
            let week = dt.format("%Y-W%V").to_string();
            let entry = weekly_agg.entry(week).or_insert((0, HashSet::new()));
            entry.0 += 1;
            entry.1.insert(m.session_id.clone());
        }
    }
    let mut weekly_data: Vec<WeeklyData> = weekly_agg.into_iter().map(|(w, (u, s))| {
        WeeklyData { week: w, user_msgs: u, sessions: s.len() as i64 }
    }).collect();
    weekly_data.sort_by(|a, b| a.week.cmp(&b.week));

    // Efficiency by start hour
    struct HourEff {
        total_msgs: i64,
        sessions: i64,
        duration_total: f64,
    }
    let mut hour_eff: HashMap<u32, HourEff> = HashMap::new();
    for sd in &session_durations {
        let entry = hour_eff.entry(sd.start_hour).or_insert(HourEff { total_msgs: 0, sessions: 0, duration_total: 0.0 });
        entry.total_msgs += sd.user_msgs + sd.assistant_msgs;
        entry.sessions += 1;
        entry.duration_total += sd.duration_min;
    }
    let mut efficiency_data: Vec<EfficiencyData> = hour_eff.into_iter()
        .filter(|(_, e)| e.sessions > 0)
        .map(|(h, e)| {
            EfficiencyData {
                hour: h,
                avg_msgs_per_session: (e.total_msgs as f64 / e.sessions as f64 * 10.0).round() / 10.0,
                avg_duration: (e.duration_total / e.sessions as f64 * 10.0).round() / 10.0,
                sessions: e.sessions,
            }
        })
        .collect();
    efficiency_data.sort_by(|a, b| a.hour.cmp(&b.hour));

    // Working hours estimate
    struct DaySpan {
        times: Vec<DateTime<FixedOffset>>,
    }
    let mut daily_spans: HashMap<String, DaySpan> = HashMap::new();
    for m in &user_messages {
        if let Some(parsed) = parse_timestamp(&m.timestamp) {
            let dt = apply_tz_offset(&parsed, tz_offset);
            let day = dt.format("%Y-%m-%d").to_string();
            daily_spans.entry(day).or_insert(DaySpan { times: Vec::new() }).times.push(dt);
        }
    }

    let mut work_days: Vec<WorkDay> = Vec::new();
    let mut sorted_days: Vec<(String, DaySpan)> = daily_spans.into_iter().collect();
    sorted_days.sort_by(|a, b| a.0.cmp(&b.0));
    for (day, mut span) in sorted_days {
        span.times.sort();
        let span_hrs = (*span.times.last().unwrap() - *span.times.first().unwrap()).num_seconds() as f64 / 3600.0;
        let mut active_secs: f64 = 120.0;
        for i in 1..span.times.len() {
            let gap = (span.times[i] - span.times[i - 1]).num_seconds() as f64;
            active_secs += gap.min(1800.0);
        }
        let active_hrs = active_secs / 3600.0;
        work_days.push(WorkDay {
            date: day,
            first: span.times.first().unwrap().format("%H:%M").to_string(),
            last: span.times.last().unwrap().format("%H:%M").to_string(),
            span_hrs: (span_hrs * 10.0).round() / 10.0,
            active_hrs: (active_hrs * 10.0).round() / 10.0,
            prompts: span.times.len() as i64,
        });
    }

    // Prompt analysis
    let mut cat_counts: HashMap<String, i64> = HashMap::new();
    let mut lb_counts: HashMap<String, i64> = HashMap::new();

    struct ProjQualityAccum {
        count: i64,
        total_len: i64,
        confirms: i64,
        detailed: i64,
        cats: HashMap<String, i64>,
    }
    let mut proj_quality: HashMap<String, ProjQualityAccum> = HashMap::new();

    for p in &prompts {
        *cat_counts.entry(p.category.clone()).or_insert(0) += 1;
        *lb_counts.entry(p.length_bucket.clone()).or_insert(0) += 1;

        let pq = proj_quality.entry(p.project.clone()).or_insert(ProjQualityAccum {
            count: 0, total_len: 0, confirms: 0, detailed: 0, cats: HashMap::new(),
        });
        pq.count += 1;
        pq.total_len += p.full_length;
        if p.category == "confirmation" || p.category == "micro" {
            pq.confirms += 1;
        }
        if p.full_length > 100 {
            pq.detailed += 1;
        }
        *pq.cats.entry(p.category.clone()).or_insert(0) += 1;
    }

    let total_prompts = prompts.len() as i64;
    let avg_length = if total_prompts > 0 {
        (prompts.iter().map(|p| p.full_length).sum::<i64>() as f64 / total_prompts as f64).round() as i64
    } else {
        0
    };

    let categories: Vec<CategoryStat> = {
        let mut sorted: Vec<(String, i64)> = cat_counts.into_iter().collect();
        sorted.sort_by(|a, b| b.1.cmp(&a.1));
        sorted.into_iter().map(|(c, n)| {
            let pct = if total_prompts > 0 { (n as f64 / total_prompts as f64 * 1000.0).round() / 10.0 } else { 0.0 };
            CategoryStat { cat: c, count: n, pct }
        }).collect()
    };

    let bucket_order = ["micro (<20)", "short (20-50)", "medium (50-150)", "detailed (150-500)", "comprehensive (500+)"];
    let length_buckets: Vec<LengthBucketStat> = bucket_order.iter().map(|b| {
        let count = lb_counts.get(*b).copied().unwrap_or(0);
        let pct = if total_prompts > 0 { (count as f64 / total_prompts as f64 * 1000.0).round() / 10.0 } else { 0.0 };
        LengthBucketStat { bucket: b.to_string(), count, pct }
    }).collect();

    let mut project_quality_data: Vec<ProjectQuality> = proj_quality.into_iter()
        .filter(|(_, d)| d.count >= 5)
        .map(|(p, d)| {
            let top_cat = d.cats.iter().max_by_key(|(_, v)| *v).map(|(k, _)| k.clone()).unwrap_or_default();
            ProjectQuality {
                project: p,
                count: d.count,
                avg_len: (d.total_len as f64 / d.count as f64).round() as i64,
                confirm_pct: (d.confirms as f64 / d.count as f64 * 1000.0).round() / 10.0,
                detailed_pct: (d.detailed as f64 / d.count as f64 * 1000.0).round() / 10.0,
                top_cat,
            }
        })
        .collect();
    project_quality_data.sort_by(|a, b| b.count.cmp(&a.count));

    let analysis = Analysis {
        total_prompts,
        avg_length,
        categories,
        length_buckets,
        project_quality: project_quality_data,
    };

    // === Model breakdown ===
    let total_output: i64 = model_counts.values().map(|v| v.output).sum();
    let total_input: i64 = model_counts.values().map(|v| v.input).sum();
    let total_cache_read: i64 = model_counts.values().map(|v| v.cache_read).sum();
    let total_cache_write: i64 = model_counts.values().map(|v| v.cache_write).sum();

    let model_breakdown: Vec<ModelBreakdown> = {
        let mut sorted: Vec<(String, &ModelAccum)> = model_counts.iter().map(|(k, v)| (k.clone(), v)).collect();
        sorted.sort_by(|a, b| b.1.msgs.cmp(&a.1.msgs));
        sorted.into_iter().map(|(raw_model, counts)| {
            let display = normalize_model_name(&raw_model);
            let cost_tier = match_model_cost(&raw_model);
            let cost = counts.input as f64 / 1_000_000.0 * cost_tier.input
                + counts.output as f64 / 1_000_000.0 * cost_tier.output
                + counts.cache_read as f64 / 1_000_000.0 * cost_tier.cache_read
                + counts.cache_write as f64 / 1_000_000.0 * cost_tier.cache_write;
            ModelBreakdown {
                model: raw_model,
                display,
                msgs: counts.msgs,
                input_tokens: counts.input,
                output_tokens: counts.output,
                cache_read_tokens: counts.cache_read,
                cache_write_tokens: counts.cache_write,
                estimated_cost: (cost * 100.0).round() / 100.0,
            }
        }).collect()
    };

    // === Cost estimation ===
    let mut total_cost: f64 = model_breakdown.iter().map(|m| m.estimated_cost).sum();

    // === Subagent analysis ===
    let mut subagent_data = parse_subagents(claude_dir, tz_offset);

    // Add subagent costs
    let mut subagent_cost: f64 = 0.0;
    for (_raw_model, tokens) in &subagent_data.model_tokens {
        let cost_tier = match_model_cost(_raw_model);
        subagent_cost += tokens.input as f64 / 1_000_000.0 * cost_tier.input
            + tokens.output as f64 / 1_000_000.0 * cost_tier.output
            + tokens.cache_read as f64 / 1_000_000.0 * cost_tier.cache_read;
    }
    subagent_data.estimated_cost = (subagent_cost * 100.0).round() / 100.0;
    total_cost += subagent_cost;

    // === Git branch data ===
    let mut branch_data: Vec<BranchData> = branch_activity.into_iter().map(|(br, (msgs, sessions, projects))| {
        BranchData {
            branch: br,
            msgs,
            sessions: sessions.len() as i64,
            projects: projects.into_iter().collect(),
        }
    }).collect();
    branch_data.sort_by(|a, b| b.msgs.cmp(&a.msgs));
    branch_data.truncate(20);

    // === Context efficiency ===
    let subagent_output_tokens = subagent_data.total_subagent_output_tokens;
    let total_all_output = total_output + subagent_output_tokens;
    let context_efficiency = ContextEfficiency {
        tool_output_tokens: total_tool_result_tokens,
        conversation_tokens: total_conversation_tokens,
        tool_pct: (total_tool_result_tokens as f64 / total_output.max(1) as f64 * 1000.0).round() / 10.0,
        conversation_pct: (total_conversation_tokens as f64 / total_output.max(1) as f64 * 1000.0).round() / 10.0,
        thinking_blocks: thinking_count,
        subagent_output_tokens,
        subagent_pct: (subagent_output_tokens as f64 / total_all_output.max(1) as f64 * 1000.0).round() / 10.0,
    };

    // === Version tracking ===
    let version_data: Vec<VersionData> = {
        let mut sorted: Vec<(String, i64)> = version_counts.into_iter().collect();
        sorted.sort_by(|a, b| b.1.cmp(&a.1));
        sorted.truncate(10);
        sorted.into_iter().map(|(v, c)| VersionData { version: v, count: c }).collect()
    };

    // === Skill/MCP usage ===
    let skill_data: Vec<SkillData> = {
        let mut sorted: Vec<(String, i64)> = skill_usage.into_iter().collect();
        sorted.sort_by(|a, b| b.1.cmp(&a.1));
        sorted.truncate(15);
        sorted.into_iter().map(|(s, c)| SkillData { skill: s, count: c }).collect()
    };

    // === Slash command usage ===
    let slash_command_data: Vec<SlashCommandData> = {
        let mut sorted: Vec<(String, i64)> = slash_commands.into_iter().collect();
        sorted.sort_by(|a, b| b.1.cmp(&a.1));
        sorted.truncate(15);
        sorted.into_iter().map(|(cmd, c)| SlashCommandData { command: cmd, count: c }).collect()
    };

    // Config
    let config = parse_config(claude_dir);

    let total_tool_calls: i64 = asst_messages.iter().map(|m| m.tool_uses.len() as i64).sum();
    let avg_session_duration = if session_durations.is_empty() {
        0.0
    } else {
        let total: f64 = session_durations.iter().map(|s| s.duration_min).sum();
        (total / session_durations.len() as f64 * 10.0).round() / 10.0
    };

    let summary = Summary {
        total_sessions: sessions_meta.len() as i64,
        total_user_msgs: user_messages.len() as i64,
        total_assistant_msgs: asst_messages.len() as i64,
        total_tool_calls,
        total_output_tokens: total_output,
        total_input_tokens: total_input,
        total_cache_read_tokens: total_cache_read,
        total_cache_write_tokens: total_cache_write,
        date_range_start: all_dates.first().cloned().unwrap_or_default(),
        date_range_end: all_dates.last().cloned().unwrap_or_default(),
        since_date: since_date.unwrap_or("").to_string(),
        unique_projects: project_stats.len() as i64,
        unique_tools: tool_data.len() as i64,
        avg_session_duration,
        tz_offset,
        tz_label: format!("UTC{:+}", tz_offset),
        estimated_cost: (total_cost * 100.0).round() / 100.0,
        skipped_files,
        skipped_lines,
    };

    Ok(ParseResult {
        dashboard: Dashboard {
            summary,
            daily: daily_data,
            heatmap: heatmap_data,
            projects: project_data,
            tools: tool_data,
            hourly: hourly_data,
            sessions: session_durations,
            weekly: weekly_data,
            efficiency: efficiency_data,
        },
        drilldown,
        analysis,
        prompts,
        work_days,
        models: model_breakdown,
        subagents: subagent_data,
        branches: branch_data,
        context_efficiency,
        versions: version_data,
        skills: skill_data,
        slash_commands: slash_command_data,
        permission_modes,
        config,
    })
}

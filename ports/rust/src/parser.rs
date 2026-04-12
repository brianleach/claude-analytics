use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

use chrono::{DateTime, FixedOffset, Local, NaiveDateTime, Datelike, Timelike};
use regex::Regex;
use serde_json::Value;

/// Truncate a string to at most `max` bytes, ensuring we don't split a multi-byte char.
fn truncate(s: &str, max: usize) -> &str {
    if s.len() <= max { return s; }
    let mut end = max;
    while end > 0 && !s.is_char_boundary(end) { end -= 1; }
    &s[..end]
}

// === COST ESTIMATES (per million tokens, USD) ===
pub struct ModelCost {
    pub input: f64,
    pub output: f64,
    pub cache_read: f64,
    pub cache_write: f64,
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

pub fn parse_config(claude_dir: &Path) -> Value {
    let config_path = claude_dir.join(".claude.json");
    let mut config = serde_json::json!({
        "has_config": false,
        "plugins": [],
        "feature_flags": [],
        "version_info": {},
    });

    if !config_path.exists() {
        return config;
    }

    if let Ok(contents) = fs::read_to_string(&config_path) {
        if let Ok(data) = serde_json::from_str::<Value>(&contents) {
            config["has_config"] = Value::Bool(true);

            // Extract plugins
            if let Some(features) = data.get("cachedGrowthBookFeatures").and_then(|v| v.as_object()) {
                if let Some(amber_lattice) = features.get("tengu_amber_lattice").and_then(|v| v.as_object()) {
                    if let Some(plugins) = amber_lattice.get("value").and_then(|v| v.as_array()) {
                        let plugin_list: Vec<Value> = plugins.iter()
                            .filter_map(|p| p.as_str().map(|s| Value::String(s.to_string())))
                            .collect();
                        config["plugins"] = Value::Array(plugin_list);
                    }
                }

                // Extract feature flags
                let mut flag_names = Vec::new();
                for (key, val) in features {
                    let clean_name = key.replace("tengu_", "");
                    if let Some(obj) = val.as_object() {
                        let enabled = obj.get("value").map(|v| v.as_bool().unwrap_or(false)).unwrap_or(false);
                        flag_names.push(serde_json::json!({
                            "name": clean_name,
                            "enabled": enabled,
                        }));
                    } else if let Some(b) = val.as_bool() {
                        flag_names.push(serde_json::json!({
                            "name": clean_name,
                            "enabled": b,
                        }));
                    }
                }
                config["feature_flags"] = Value::Array(flag_names);
            }

            // Migration / account info
            config["version_info"] = serde_json::json!({
                "migration_version": data.get("migrationVersion").and_then(|v| v.as_str()).unwrap_or(""),
                "first_start": data.get("firstStartTime").and_then(|v| v.as_str()).unwrap_or(""),
            });
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

pub fn parse_subagents(claude_dir: &Path, tz_offset: i32) -> Value {
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

    let mut subagents: Vec<Value> = Vec::new();
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

        let agent_id_short = truncate(&agent_id, 12);
        let desc_short = truncate(&description, 80);

        let models_vec: Vec<Value> = models_used.iter().map(|m| Value::String(m.clone())).collect();

        subagents.push(serde_json::json!({
            "agent_id": agent_id_short,
            "type": agent_type,
            "description": desc_short,
            "is_compaction": is_compaction,
            "project": proj_name,
            "messages": msg_count,
            "tool_calls": tool_calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_tokens": cache_read,
            "models": models_vec,
            "duration_min": (duration * 10.0).round() / 10.0,
        }));

        // Accumulate tokens by model for subagents
        let num_models = models_used.len().max(1) as i64;
        for m in &models_used {
            let entry = model_tokens.entry(m.clone()).or_insert((0, 0, 0));
            entry.0 += input_tokens / num_models;
            entry.1 += output_tokens / num_models;
            entry.2 += cache_read / num_models;
        }
    }

    let type_counts_val: Value = serde_json::to_value(&type_counts).unwrap_or(Value::Object(Default::default()));

    let model_tokens_val: Value = {
        let mut map = serde_json::Map::new();
        for (model, (inp, out, cr)) in &model_tokens {
            map.insert(model.clone(), serde_json::json!({
                "input": inp,
                "output": out,
                "cache_read": cr,
            }));
        }
        Value::Object(map)
    };

    let compaction_count = subagents.iter().filter(|s| s["is_compaction"].as_bool().unwrap_or(false)).count();
    let total_input: i64 = subagents.iter().map(|s| s["input_tokens"].as_i64().unwrap_or(0)).sum();
    let total_output: i64 = subagents.iter().map(|s| s["output_tokens"].as_i64().unwrap_or(0)).sum();

    serde_json::json!({
        "subagents": subagents,
        "type_counts": type_counts_val,
        "total_count": subagents.len(),
        "compaction_count": compaction_count,
        "total_subagent_input_tokens": total_input,
        "total_subagent_output_tokens": total_output,
        "model_tokens": model_tokens_val,
    })
}

pub fn parse_all_sessions(claude_dir: &Path, tz_offset: Option<i32>, since_date: Option<&str>) -> Result<Value, String> {
    let tz_offset = tz_offset.unwrap_or_else(detect_timezone_offset);
    let session_files = find_session_files(claude_dir)?;

    if session_files.is_empty() {
        return Err("No session files found. Use Claude Code for a while first!".to_string());
    }

    // === Pass 1: Extract all messages ===
    let mut all_messages: Vec<Value> = Vec::new();
    let mut sessions_meta: Vec<Value> = Vec::new();
    let mut prompts: Vec<Value> = Vec::new();
    // drilldown: date -> project -> list of prompts
    let mut drilldown: HashMap<String, HashMap<String, Vec<Value>>> = HashMap::new();

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
        let session_id_short = truncate(&session_id, 8);

        let mut timestamps: Vec<String> = Vec::new();
        let mut user_msgs: i64 = 0;
        let mut assistant_msgs: i64 = 0;
        let mut tool_uses: i64 = 0;
        let mut model: String = String::new();
        let mut entrypoint: Option<String> = None;
        let mut git_branch: Option<String> = None;
        let mut session_input_tokens: i64 = 0;
        let mut session_output_tokens: i64 = 0;
        let mut session_cache_read: i64 = 0;
        let mut session_cache_write: i64 = 0;

        let contents = match fs::read_to_string(filepath) {
            Ok(c) => c,
            Err(_) => continue,
        };

        for line in contents.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let d: Value = match serde_json::from_str(line) {
                Ok(v) => v,
                Err(_) => continue,
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
                if entrypoint.is_none() {
                    entrypoint = d.get("entrypoint").and_then(|v| v.as_str()).map(|s| s.to_string());
                }

                let hour = dt.hour() as i64;
                let weekday = dt.weekday().num_days_from_monday() as i64;
                let weekday_name = weekday_names[weekday as usize];
                let time_str = dt.format("%H:%M").to_string();
                let month_str = dt.format("%Y-%m").to_string();

                let msg_data = serde_json::json!({
                    "timestamp": ts,
                    "date": date_str,
                    "time": time_str,
                    "hour": hour,
                    "weekday": weekday,
                    "weekday_name": weekday_name,
                    "month": month_str,
                    "type": "user",
                    "project": proj_name,
                    "session_id": session_id_short,
                });
                all_messages.push(msg_data);
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
                    let full_length = text.len();
                    let text_short = truncate(&text, 500);
                    let category = categorize_prompt(&text);
                    let lb = length_bucket(full_length);

                    let prompt = serde_json::json!({
                        "text": text_short,
                        "full_length": full_length,
                        "project": proj_name,
                        "session_id": session_id_short,
                        "date": date_str,
                        "time": time_str,
                        "hour": hour,
                        "weekday": weekday,
                        "category": category,
                        "length_bucket": lb,
                    });
                    prompts.push(prompt);

                    let text_drilldown = truncate(&text, 200);
                    let drill_entry = serde_json::json!({
                        "time": time_str,
                        "text": text_drilldown,
                        "category": category,
                        "length": full_length,
                    });
                    drilldown
                        .entry(date_str.clone())
                        .or_default()
                        .entry(proj_name.clone())
                        .or_default()
                        .push(drill_entry);
                }

                // Track branch activity
                if let Some(ref br) = git_branch {
                    let entry = branch_activity.entry(br.clone()).or_insert_with(|| (0, HashSet::new(), HashSet::new()));
                    entry.0 += 1;
                    entry.1.insert(session_id_short.to_string());
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

                let tools_val: Vec<Value> = msg_tools.iter().map(|t| Value::String(t.clone())).collect();
                all_messages.push(serde_json::json!({
                    "timestamp": ts,
                    "date": date_str,
                    "hour": dt.hour(),
                    "weekday": dt.weekday().num_days_from_monday(),
                    "type": "assistant",
                    "project": proj_name,
                    "session_id": session_id_short,
                    "tool_uses": tools_val,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model": msg_model,
                }));
            }
        }

        if !timestamps.is_empty() {
            timestamps.sort();
            sessions_meta.push(serde_json::json!({
                "project": proj_name,
                "session_id": session_id_short,
                "first_ts": timestamps.first().unwrap(),
                "last_ts": timestamps.last().unwrap(),
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
            }));
        }
    }

    // === Pass 2: Aggregate ===
    let user_messages: Vec<&Value> = all_messages.iter().filter(|m| m["type"] == "user").collect();
    let asst_messages: Vec<&Value> = all_messages.iter().filter(|m| m["type"] == "assistant").collect();

    // Daily data
    let mut daily_user: HashMap<String, i64> = HashMap::new();
    let mut daily_asst: HashMap<String, i64> = HashMap::new();
    let mut daily_tools: HashMap<String, i64> = HashMap::new();
    let mut daily_tokens: HashMap<String, i64> = HashMap::new();

    for m in &user_messages {
        let date = m["date"].as_str().unwrap_or("");
        *daily_user.entry(date.to_string()).or_insert(0) += 1;
    }
    for m in &asst_messages {
        let date = m["date"].as_str().unwrap_or("");
        *daily_asst.entry(date.to_string()).or_insert(0) += 1;
        let tool_count = m["tool_uses"].as_array().map(|a| a.len() as i64).unwrap_or(0);
        *daily_tools.entry(date.to_string()).or_insert(0) += tool_count;
        *daily_tokens.entry(date.to_string()).or_insert(0) += m["output_tokens"].as_i64().unwrap_or(0);
    }

    let mut all_dates: Vec<String> = {
        let mut s: HashSet<String> = HashSet::new();
        for k in daily_user.keys() { s.insert(k.clone()); }
        for k in daily_asst.keys() { s.insert(k.clone()); }
        s.into_iter().collect()
    };
    all_dates.sort();

    let daily_data: Vec<Value> = all_dates.iter().map(|d| {
        let u = daily_user.get(d).copied().unwrap_or(0);
        let a = daily_asst.get(d).copied().unwrap_or(0);
        serde_json::json!({
            "date": d,
            "user_msgs": u,
            "assistant_msgs": a,
            "tool_calls": daily_tools.get(d).copied().unwrap_or(0),
            "output_tokens": daily_tokens.get(d).copied().unwrap_or(0),
            "total_msgs": u + a,
        })
    }).collect();

    // Heatmap
    let mut heatmap_counts: HashMap<String, i64> = HashMap::new();
    for m in &user_messages {
        let wd = m["weekday"].as_i64().unwrap_or(0);
        let hr = m["hour"].as_i64().unwrap_or(0);
        *heatmap_counts.entry(format!("{}_{}", wd, hr)).or_insert(0) += 1;
    }
    let mut heatmap_data: Vec<Value> = Vec::new();
    for wd in 0..7 {
        for hr in 0..24 {
            heatmap_data.push(serde_json::json!({
                "weekday": wd,
                "hour": hr,
                "count": heatmap_counts.get(&format!("{}_{}", wd, hr)).copied().unwrap_or(0),
            }));
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
        let p = m["project"].as_str().unwrap_or("unknown").to_string();
        let ps = project_stats.entry(p).or_insert(ProjStats {
            user_msgs: 0, assistant_msgs: 0, tool_calls: 0, sessions: HashSet::new(), output_tokens: 0,
        });
        ps.sessions.insert(m.get("session_id").and_then(|v| v.as_str()).unwrap_or("").to_string());
        if m["type"] == "user" {
            ps.user_msgs += 1;
        } else {
            ps.assistant_msgs += 1;
            ps.tool_calls += m["tool_uses"].as_array().map(|a| a.len() as i64).unwrap_or(0);
            ps.output_tokens += m["output_tokens"].as_i64().unwrap_or(0);
        }
    }

    let mut project_data: Vec<Value> = project_stats.iter().map(|(p, s)| {
        serde_json::json!({
            "project": p,
            "user_msgs": s.user_msgs,
            "assistant_msgs": s.assistant_msgs,
            "tool_calls": s.tool_calls,
            "sessions": s.sessions.len(),
            "output_tokens": s.output_tokens,
            "total_msgs": s.user_msgs + s.assistant_msgs,
        })
    }).collect();
    project_data.sort_by(|a, b| b["total_msgs"].as_i64().unwrap_or(0).cmp(&a["total_msgs"].as_i64().unwrap_or(0)));

    // Tool stats
    let mut tool_counts: HashMap<String, i64> = HashMap::new();
    for m in &asst_messages {
        if let Some(tools) = m["tool_uses"].as_array() {
            for t in tools {
                if let Some(name) = t.as_str() {
                    *tool_counts.entry(name.to_string()).or_insert(0) += 1;
                }
            }
        }
    }
    let mut tool_data_vec: Vec<(String, i64)> = tool_counts.into_iter().collect();
    tool_data_vec.sort_by(|a, b| b.1.cmp(&a.1));
    tool_data_vec.truncate(20);
    let tool_data: Vec<Value> = tool_data_vec.into_iter()
        .map(|(t, c)| serde_json::json!({"tool": t, "count": c}))
        .collect();

    // Hourly
    let mut hourly_counts: HashMap<i64, i64> = HashMap::new();
    for m in &user_messages {
        let h = m["hour"].as_i64().unwrap_or(0);
        *hourly_counts.entry(h).or_insert(0) += 1;
    }
    let hourly_data: Vec<Value> = (0..24).map(|h| {
        serde_json::json!({"hour": h, "count": hourly_counts.get(&h).copied().unwrap_or(0)})
    }).collect();

    // Session durations
    let mut session_durations: Vec<Value> = Vec::new();
    for s in &sessions_meta {
        let first_ts = s["first_ts"].as_str().unwrap_or("");
        let last_ts = s["last_ts"].as_str().unwrap_or("");
        if let (Some(t1), Some(t2)) = (parse_timestamp(first_ts), parse_timestamp(last_ts)) {
            let dur = (t2 - t1).num_seconds() as f64 / 60.0;
            let t1_local = apply_tz_offset(&t1, tz_offset);
            let msg_count = s["user_msgs"].as_i64().unwrap_or(0) + s["assistant_msgs"].as_i64().unwrap_or(0);
            let msgs_per_min = if dur > 0.0 { (msg_count as f64 / dur * 100.0).round() / 100.0 } else { 0.0 };
            session_durations.push(serde_json::json!({
                "session_id": s["session_id"],
                "project": s["project"],
                "duration_min": (dur * 10.0).round() / 10.0,
                "user_msgs": s["user_msgs"],
                "assistant_msgs": s["assistant_msgs"],
                "tool_uses": s["tool_uses"],
                "date": t1_local.format("%Y-%m-%d").to_string(),
                "start_hour": t1_local.hour(),
                "msgs_per_min": msgs_per_min,
                "git_branch": s["git_branch"],
            }));
        }
    }

    // Weekly
    let mut weekly_agg: HashMap<String, (i64, HashSet<String>)> = HashMap::new();
    for m in &user_messages {
        let ts_str = m["timestamp"].as_str().unwrap_or("");
        if let Some(dt) = parse_timestamp(ts_str) {
            let week = dt.format("%Y-W%V").to_string();
            let entry = weekly_agg.entry(week).or_insert((0, HashSet::new()));
            entry.0 += 1;
            entry.1.insert(m["session_id"].as_str().unwrap_or("").to_string());
        }
    }
    let mut weekly_data: Vec<Value> = weekly_agg.into_iter().map(|(w, (u, s))| {
        serde_json::json!({"week": w, "user_msgs": u, "sessions": s.len()})
    }).collect();
    weekly_data.sort_by(|a, b| a["week"].as_str().unwrap_or("").cmp(b["week"].as_str().unwrap_or("")));

    // Efficiency by start hour
    struct HourEff {
        total_msgs: i64,
        sessions: i64,
        duration_total: f64,
    }
    let mut hour_eff: HashMap<u32, HourEff> = HashMap::new();
    for sd in &session_durations {
        let h = sd["start_hour"].as_u64().unwrap_or(0) as u32;
        let entry = hour_eff.entry(h).or_insert(HourEff { total_msgs: 0, sessions: 0, duration_total: 0.0 });
        entry.total_msgs += sd["user_msgs"].as_i64().unwrap_or(0) + sd["assistant_msgs"].as_i64().unwrap_or(0);
        entry.sessions += 1;
        entry.duration_total += sd["duration_min"].as_f64().unwrap_or(0.0);
    }
    let mut efficiency_data: Vec<Value> = hour_eff.into_iter()
        .filter(|(_, e)| e.sessions > 0)
        .map(|(h, e)| {
            serde_json::json!({
                "hour": h,
                "avg_msgs_per_session": (e.total_msgs as f64 / e.sessions as f64 * 10.0).round() / 10.0,
                "avg_duration": (e.duration_total / e.sessions as f64 * 10.0).round() / 10.0,
                "sessions": e.sessions,
            })
        })
        .collect();
    efficiency_data.sort_by(|a, b| a["hour"].as_u64().unwrap_or(0).cmp(&b["hour"].as_u64().unwrap_or(0)));

    // Working hours estimate
    struct DaySpan {
        times: Vec<DateTime<FixedOffset>>,
    }
    let mut daily_spans: HashMap<String, DaySpan> = HashMap::new();
    for m in &user_messages {
        let ts_str = m["timestamp"].as_str().unwrap_or("");
        if let Some(parsed) = parse_timestamp(ts_str) {
            let dt = apply_tz_offset(&parsed, tz_offset);
            let day = dt.format("%Y-%m-%d").to_string();
            daily_spans.entry(day).or_insert(DaySpan { times: Vec::new() }).times.push(dt);
        }
    }

    let mut work_days: Vec<Value> = Vec::new();
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
        work_days.push(serde_json::json!({
            "date": day,
            "first": span.times.first().unwrap().format("%H:%M").to_string(),
            "last": span.times.last().unwrap().format("%H:%M").to_string(),
            "span_hrs": (span_hrs * 10.0).round() / 10.0,
            "active_hrs": (active_hrs * 10.0).round() / 10.0,
            "prompts": span.times.len(),
        }));
    }

    // Prompt analysis
    let mut cat_counts: HashMap<String, i64> = HashMap::new();
    let mut lb_counts: HashMap<String, i64> = HashMap::new();

    struct ProjQuality {
        count: i64,
        total_len: i64,
        confirms: i64,
        detailed: i64,
        cats: HashMap<String, i64>,
    }
    let mut proj_quality: HashMap<String, ProjQuality> = HashMap::new();

    for p in &prompts {
        let cat = p["category"].as_str().unwrap_or("").to_string();
        let lb = p["length_bucket"].as_str().unwrap_or("").to_string();
        let proj = p["project"].as_str().unwrap_or("").to_string();
        let full_len = p["full_length"].as_i64().unwrap_or(0);

        *cat_counts.entry(cat.clone()).or_insert(0) += 1;
        *lb_counts.entry(lb).or_insert(0) += 1;

        let pq = proj_quality.entry(proj).or_insert(ProjQuality {
            count: 0, total_len: 0, confirms: 0, detailed: 0, cats: HashMap::new(),
        });
        pq.count += 1;
        pq.total_len += full_len;
        if cat == "confirmation" || cat == "micro" {
            pq.confirms += 1;
        }
        if full_len > 100 {
            pq.detailed += 1;
        }
        *pq.cats.entry(cat).or_insert(0) += 1;
    }

    let total_prompts = prompts.len() as i64;
    let avg_length = if total_prompts > 0 {
        (prompts.iter().map(|p| p["full_length"].as_i64().unwrap_or(0)).sum::<i64>() as f64 / total_prompts as f64).round() as i64
    } else {
        0
    };

    let categories: Vec<Value> = {
        let mut sorted: Vec<(String, i64)> = cat_counts.into_iter().collect();
        sorted.sort_by(|a, b| b.1.cmp(&a.1));
        sorted.into_iter().map(|(c, n)| {
            let pct = if total_prompts > 0 { (n as f64 / total_prompts as f64 * 1000.0).round() / 10.0 } else { 0.0 };
            serde_json::json!({"cat": c, "count": n, "pct": pct})
        }).collect()
    };

    let bucket_order = ["micro (<20)", "short (20-50)", "medium (50-150)", "detailed (150-500)", "comprehensive (500+)"];
    let length_buckets: Vec<Value> = bucket_order.iter().map(|b| {
        let count = lb_counts.get(*b).copied().unwrap_or(0);
        let pct = if total_prompts > 0 { (count as f64 / total_prompts as f64 * 1000.0).round() / 10.0 } else { 0.0 };
        serde_json::json!({"bucket": b, "count": count, "pct": pct})
    }).collect();

    let mut project_quality: Vec<Value> = proj_quality.into_iter()
        .filter(|(_, d)| d.count >= 5)
        .map(|(p, d)| {
            let top_cat = d.cats.iter().max_by_key(|(_, v)| *v).map(|(k, _)| k.clone()).unwrap_or_default();
            serde_json::json!({
                "project": p,
                "count": d.count,
                "avg_len": (d.total_len as f64 / d.count as f64).round() as i64,
                "confirm_pct": (d.confirms as f64 / d.count as f64 * 1000.0).round() / 10.0,
                "detailed_pct": (d.detailed as f64 / d.count as f64 * 1000.0).round() / 10.0,
                "top_cat": top_cat,
            })
        })
        .collect();
    project_quality.sort_by(|a, b| b["count"].as_i64().unwrap_or(0).cmp(&a["count"].as_i64().unwrap_or(0)));

    let analysis = serde_json::json!({
        "total_prompts": total_prompts,
        "avg_length": avg_length,
        "categories": categories,
        "length_buckets": length_buckets,
        "project_quality": project_quality,
    });

    // === Model breakdown ===
    let total_output: i64 = model_counts.values().map(|v| v.output).sum();
    let total_input: i64 = model_counts.values().map(|v| v.input).sum();
    let total_cache_read: i64 = model_counts.values().map(|v| v.cache_read).sum();
    let total_cache_write: i64 = model_counts.values().map(|v| v.cache_write).sum();

    let model_breakdown: Vec<Value> = {
        let mut sorted: Vec<(String, &ModelAccum)> = model_counts.iter().map(|(k, v)| (k.clone(), v)).collect();
        sorted.sort_by(|a, b| b.1.msgs.cmp(&a.1.msgs));
        sorted.into_iter().map(|(raw_model, counts)| {
            let display = normalize_model_name(&raw_model);
            let cost_tier = match_model_cost(&raw_model);
            let cost = counts.input as f64 / 1_000_000.0 * cost_tier.input
                + counts.output as f64 / 1_000_000.0 * cost_tier.output
                + counts.cache_read as f64 / 1_000_000.0 * cost_tier.cache_read
                + counts.cache_write as f64 / 1_000_000.0 * cost_tier.cache_write;
            serde_json::json!({
                "model": raw_model,
                "display": display,
                "msgs": counts.msgs,
                "input_tokens": counts.input,
                "output_tokens": counts.output,
                "cache_read_tokens": counts.cache_read,
                "cache_write_tokens": counts.cache_write,
                "estimated_cost": (cost * 100.0).round() / 100.0,
            })
        }).collect()
    };

    // === Cost estimation ===
    let mut total_cost: f64 = model_breakdown.iter().map(|m| m["estimated_cost"].as_f64().unwrap_or(0.0)).sum();

    // === Subagent analysis ===
    let mut subagent_data = parse_subagents(claude_dir, tz_offset);

    // Add subagent costs
    let mut subagent_cost: f64 = 0.0;
    if let Some(mt) = subagent_data.get("model_tokens").and_then(|v| v.as_object()) {
        for (raw_model, tokens) in mt {
            let cost_tier = match_model_cost(raw_model);
            let inp = tokens.get("input").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let out = tokens.get("output").and_then(|v| v.as_f64()).unwrap_or(0.0);
            let cr = tokens.get("cache_read").and_then(|v| v.as_f64()).unwrap_or(0.0);
            subagent_cost += inp / 1_000_000.0 * cost_tier.input
                + out / 1_000_000.0 * cost_tier.output
                + cr / 1_000_000.0 * cost_tier.cache_read;
        }
    }
    subagent_data["estimated_cost"] = serde_json::json!((subagent_cost * 100.0).round() / 100.0);
    total_cost += subagent_cost;

    // === Git branch data ===
    let mut branch_data: Vec<Value> = branch_activity.into_iter().map(|(br, (msgs, sessions, projects))| {
        serde_json::json!({
            "branch": br,
            "msgs": msgs,
            "sessions": sessions.len(),
            "projects": projects.into_iter().collect::<Vec<_>>(),
        })
    }).collect();
    branch_data.sort_by(|a, b| b["msgs"].as_i64().unwrap_or(0).cmp(&a["msgs"].as_i64().unwrap_or(0)));
    branch_data.truncate(20);

    // === Context efficiency ===
    let subagent_output_tokens = subagent_data["total_subagent_output_tokens"].as_i64().unwrap_or(0);
    let total_all_output = total_output + subagent_output_tokens;
    let context_efficiency = serde_json::json!({
        "tool_output_tokens": total_tool_result_tokens,
        "conversation_tokens": total_conversation_tokens,
        "tool_pct": (total_tool_result_tokens as f64 / total_output.max(1) as f64 * 1000.0).round() / 10.0,
        "conversation_pct": (total_conversation_tokens as f64 / total_output.max(1) as f64 * 1000.0).round() / 10.0,
        "thinking_blocks": thinking_count,
        "subagent_output_tokens": subagent_output_tokens,
        "subagent_pct": (subagent_output_tokens as f64 / total_all_output.max(1) as f64 * 1000.0).round() / 10.0,
    });

    // === Version tracking ===
    let version_data: Vec<Value> = {
        let mut sorted: Vec<(String, i64)> = version_counts.into_iter().collect();
        sorted.sort_by(|a, b| b.1.cmp(&a.1));
        sorted.truncate(10);
        sorted.into_iter().map(|(v, c)| serde_json::json!({"version": v, "count": c})).collect()
    };

    // === Skill/MCP usage ===
    let skill_data: Vec<Value> = {
        let mut sorted: Vec<(String, i64)> = skill_usage.into_iter().collect();
        sorted.sort_by(|a, b| b.1.cmp(&a.1));
        sorted.truncate(15);
        sorted.into_iter().map(|(s, c)| serde_json::json!({"skill": s, "count": c})).collect()
    };

    // === Slash command usage ===
    let slash_command_data: Vec<Value> = {
        let mut sorted: Vec<(String, i64)> = slash_commands.into_iter().collect();
        sorted.sort_by(|a, b| b.1.cmp(&a.1));
        sorted.truncate(15);
        sorted.into_iter().map(|(cmd, c)| serde_json::json!({"command": cmd, "count": c})).collect()
    };

    // Config
    let config = parse_config(claude_dir);

    let summary = serde_json::json!({
        "total_sessions": sessions_meta.len(),
        "total_user_msgs": user_messages.len(),
        "total_assistant_msgs": asst_messages.len(),
        "total_tool_calls": asst_messages.iter().map(|m| m["tool_uses"].as_array().map(|a| a.len() as i64).unwrap_or(0)).sum::<i64>(),
        "total_output_tokens": total_output,
        "total_input_tokens": total_input,
        "total_cache_read_tokens": total_cache_read,
        "total_cache_write_tokens": total_cache_write,
        "date_range_start": all_dates.first().cloned().unwrap_or_default(),
        "date_range_end": all_dates.last().cloned().unwrap_or_default(),
        "since_date": since_date.unwrap_or(""),
        "unique_projects": project_stats.len(),
        "unique_tools": tool_data.len(),
        "avg_session_duration": if session_durations.is_empty() { 0.0 } else {
            let total: f64 = session_durations.iter().map(|s| s["duration_min"].as_f64().unwrap_or(0.0)).sum();
            (total / session_durations.len() as f64 * 10.0).round() / 10.0
        },
        "tz_offset": tz_offset,
        "tz_label": format!("UTC{:+}", tz_offset),
        "estimated_cost": (total_cost * 100.0).round() / 100.0,
    });

    // Convert drilldown to Value
    let drilldown_val: Value = {
        let mut map = serde_json::Map::new();
        for (date, projects) in drilldown {
            let mut proj_map = serde_json::Map::new();
            for (proj, entries) in projects {
                proj_map.insert(proj, Value::Array(entries));
            }
            map.insert(date, Value::Object(proj_map));
        }
        Value::Object(map)
    };

    let permission_modes_val: Value = serde_json::to_value(&permission_modes).unwrap_or(Value::Object(Default::default()));

    Ok(serde_json::json!({
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
        "drilldown": drilldown_val,
        "analysis": analysis,
        "prompts": prompts,
        "work_days": work_days,
        "models": model_breakdown,
        "subagents": subagent_data,
        "branches": branch_data,
        "context_efficiency": context_efficiency,
        "versions": version_data,
        "skills": skill_data,
        "slash_commands": slash_command_data,
        "permission_modes": permission_modes_val,
        "config": config,
    }))
}

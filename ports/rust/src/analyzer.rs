use serde_json::Value;
use std::collections::{HashMap, HashSet};
use std::io::Write;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use regex::Regex;

use crate::parser::{ParseResult, Prompt, Recommendation, RecommendationsResult};

// Canonical source: shared/heuristic_rules.json
const HEURISTIC_RULES_JSON: &str = include_str!("../../../shared/heuristic_rules.json");

// Canonical source: shared/ai_prompt.txt
const AI_PROMPT_TEMPLATE: &str = include_str!("../../../shared/ai_prompt.txt");

fn find_example_prompts(prompts: &[Prompt], category: &str, max_count: usize, max_len: usize) -> Vec<String> {
    let mut matches: Vec<&Prompt> = prompts.iter()
        .filter(|p| p.category == category && p.text.len() > 15)
        .collect();
    matches.sort_by_key(|p| p.full_length);
    matches.iter()
        .take(max_count)
        .map(|p| {
            if p.text.len() > max_len { p.text[..max_len].to_string() } else { p.text.clone() }
        })
        .collect()
}

fn find_short_prompts(prompts: &[Prompt], max_chars: i64, max_count: usize) -> Vec<String> {
    let short: Vec<&Prompt> = prompts.iter()
        .filter(|p| p.full_length < max_chars && p.text.trim().len() > 3)
        .collect();

    let result: Vec<&Prompt> = if short.len() > max_count {
        let step = short.len() / max_count;
        (0..max_count).map(|i| short[i * step]).collect()
    } else {
        short
    };

    result.iter()
        .map(|p| {
            if p.text.len() > 80 { p.text[..80].to_string() } else { p.text.clone() }
        })
        .collect()
}

fn render_template(tmpl: &str, vals: &HashMap<&str, f64>) -> String {
    let re = Regex::new(r"\{\{(\w+)(?::([^}]+))?\}\}").unwrap();
    re.replace_all(tmpl, |caps: &regex::Captures| {
        let key = caps.get(1).unwrap().as_str();
        let fmt = caps.get(2).map(|m| m.as_str());
        let val = vals.get(key).copied().unwrap_or(0.0);
        match fmt {
            Some(f) if f.ends_with('f') && f.starts_with('.') => {
                let prec: usize = f[1..f.len()-1].parse().unwrap_or(0);
                format!("{:.prec$}", val, prec = prec)
            }
            _ => {
                if val == val.trunc() {
                    format!("{}", val as i64)
                } else {
                    format!("{}", val)
                }
            }
        }
    }).to_string()
}

fn check_rule_condition(cond: &Value, vals: &HashMap<&str, f64>) -> bool {
    let metric = cond.get("metric").and_then(|v| v.as_str()).unwrap_or("");
    let op = cond.get("operator").and_then(|v| v.as_str()).unwrap_or("");
    let metric_val = vals.get(metric).copied().unwrap_or(0.0);
    let threshold = if let Some(tm) = cond.get("threshold_metric").and_then(|v| v.as_str()) {
        vals.get(tm).copied().unwrap_or(0.0)
    } else {
        cond.get("threshold").and_then(|v| v.as_f64()).unwrap_or(0.0)
    };
    match op {
        ">" => metric_val > threshold,
        "<" => metric_val < threshold,
        ">=" => metric_val >= threshold,
        "<=" => metric_val <= threshold,
        _ => false,
    }
}

pub fn get_heuristic_recommendations(data: &ParseResult) -> Vec<Recommendation> {
    let rules: Vec<Value> = serde_json::from_str(HEURISTIC_RULES_JSON).unwrap_or_default();

    let analysis = &data.analysis;
    let summary = &data.dashboard.summary;
    let prompts = &data.prompts;
    let models = &data.models;
    let subagents = &data.subagents;
    let context_efficiency = &data.context_efficiency;
    let skills = &data.skills;
    let permission_modes = &data.permission_modes;

    let total = analysis.total_prompts as f64;
    let avg_len = analysis.avg_length as f64;

    let get_cat_pct = |name: &str| -> f64 {
        analysis.categories.iter().find(|c| c.cat == name).map(|c| c.pct).unwrap_or(0.0)
    };
    let get_lb_pct = |name: &str| -> f64 {
        analysis.length_buckets.iter().find(|l| l.bucket == name).map(|l| l.pct).unwrap_or(0.0)
    };

    let micro_pct = get_lb_pct("micro (<20)");
    let short_pct = get_lb_pct("short (20-50)");
    let debug_pct = get_cat_pct("debugging");
    let test_pct = get_cat_pct("testing");
    let ref_pct = get_cat_pct("refactoring");
    let q_pct = get_cat_pct("question");
    let build_pct = get_cat_pct("building");
    let confirm_pct = get_cat_pct("confirmation");

    let total_sessions = summary.total_sessions.max(1) as f64;
    let total_user_msgs = summary.total_user_msgs as f64;
    let avg_msgs = total_user_msgs / total_sessions;

    let mut opus_pct = 0.0f64;
    if !models.is_empty() {
        let total_cost = summary.estimated_cost;
        if let Some(opus) = models.iter().find(|m| m.display == "Opus") {
            if total_cost > 0.0 {
                opus_pct = (opus.estimated_cost / total_cost * 100.0).round();
            }
        }
    }

    let sa_count = subagents.total_count as f64;
    let explore_count = subagents.type_counts.get("Explore").copied().unwrap_or(0) as f64;
    let gp_count = subagents.type_counts.get("general-purpose").copied().unwrap_or(0) as f64;
    let compaction_count = subagents.compaction_count as f64;

    let tool_pct = context_efficiency.tool_pct;
    let conversation_pct = context_efficiency.conversation_pct;
    let thinking = context_efficiency.thinking_blocks as f64;
    let thinking_per_session = thinking / total_sessions.max(1.0);

    let skill_count = skills.len() as f64;

    let default_pm = permission_modes.get("default").copied().unwrap_or(0) as f64;
    let total_pm: f64 = (permission_modes.values().sum::<i64>() as f64).max(1.0);
    let default_pm_ratio = default_pm / total_pm;
    let default_pm_pct = default_pm_ratio * 100.0;

    let format_prompt_count = prompts.iter().filter(|p| {
        let text = p.text.to_lowercase();
        ["lint", "format", "prettier", "eslint", "formatting"].iter().any(|w| text.contains(w))
    }).count() as f64;

    let long_session_count = data.work_days.iter().filter(|s| s.active_hrs > 4.0).count() as f64;

    let mut vals: HashMap<&str, f64> = HashMap::new();
    vals.insert("total", total);
    vals.insert("avg_len", avg_len);
    vals.insert("micro_pct", micro_pct);
    vals.insert("short_pct", short_pct);
    vals.insert("micro_short_pct", micro_pct + short_pct);
    vals.insert("debug_pct", debug_pct);
    vals.insert("test_pct", test_pct);
    vals.insert("ref_pct", ref_pct);
    vals.insert("q_pct", q_pct);
    vals.insert("build_pct", build_pct);
    vals.insert("confirm_pct", confirm_pct);
    vals.insert("avg_msgs", avg_msgs);
    vals.insert("total_sessions", total_sessions);
    vals.insert("opus_pct", opus_pct);
    vals.insert("sa_count", sa_count);
    vals.insert("explore_count", explore_count);
    vals.insert("gp_count", gp_count);
    vals.insert("compaction_count", compaction_count);
    vals.insert("tool_pct", tool_pct);
    vals.insert("conversation_pct", conversation_pct);
    vals.insert("thinking", thinking);
    vals.insert("thinking_per_session", thinking_per_session);
    vals.insert("skill_count", skill_count);
    vals.insert("default_pm_ratio", default_pm_ratio);
    vals.insert("default_pm_pct", default_pm_pct);
    vals.insert("format_prompt_count", format_prompt_count);
    vals.insert("long_session_count", long_session_count);

    let mut recs: Vec<Recommendation> = Vec::new();
    let mut triggered_ids: HashSet<String> = HashSet::new();

    for rule in &rules {
        let cond = &rule["condition"];
        let ctype = cond["type"].as_str().unwrap_or("");

        let passes = match ctype {
            "simple" => check_rule_condition(cond, &vals),
            "sum_gt" => {
                let sum: f64 = cond["metrics"].as_array()
                    .map(|ms| ms.iter().filter_map(|m| m.as_str()).map(|m| vals.get(m).copied().unwrap_or(0.0)).sum())
                    .unwrap_or(0.0);
                sum > cond["threshold"].as_f64().unwrap_or(0.0)
            }
            "or" => {
                cond["conditions"].as_array()
                    .map(|cs| cs.iter().any(|c| check_rule_condition(c, &vals)))
                    .unwrap_or(false)
            }
            "compound_and" => {
                let all = cond["conditions"].as_array()
                    .map(|cs| cs.iter().all(|c| check_rule_condition(c, &vals)))
                    .unwrap_or(false);
                if !all { false }
                else if let Some(excludes) = cond.get("excludes").and_then(|v| v.as_str()) {
                    !triggered_ids.contains(excludes)
                } else {
                    true
                }
            }
            "computed" => {
                let synthetic = serde_json::json!({
                    "metric": cond.get("computed_metric").and_then(|v| v.as_str()).unwrap_or(""),
                    "operator": cond.get("operator").and_then(|v| v.as_str()).unwrap_or(""),
                    "threshold": cond.get("threshold").and_then(|v| v.as_f64()).unwrap_or(0.0)
                });
                check_rule_condition(&synthetic, &vals)
            }
            _ => false,
        };

        if !passes { continue; }

        let rule_id = rule["id"].as_str().unwrap_or("").to_string();
        triggered_ids.insert(rule_id);

        // Severity
        let mut severity = rule["severity"].as_str().unwrap_or("medium").to_string();
        if let Some(so) = rule.get("severity_override") {
            if check_rule_condition(&so["condition"], &vals) {
                severity = so["severity"].as_str().unwrap_or(&severity).to_string();
            }
        }

        // Body
        let body = if let Some(variants) = rule.get("body_variants").and_then(|v| v.as_object()) {
            let mut variant = "default";
            if let Some(bvc) = rule.get("body_variant_condition") {
                if check_rule_condition(bvc, &vals) {
                    variant = bvc.get("variant").and_then(|v| v.as_str()).unwrap_or("default");
                }
            }
            render_template(variants.get(variant).and_then(|v| v.as_str()).unwrap_or(""), &vals)
        } else {
            render_template(rule["body_template"].as_str().unwrap_or(""), &vals)
        };

        let metric = render_template(rule["metric_template"].as_str().unwrap_or(""), &vals);

        // Example
        let mut example = String::new();
        match rule.get("example_type").and_then(|v| v.as_str()) {
            Some("short_prompts") => {
                let short_examples = find_short_prompts(prompts, 50, 5);
                if !short_examples.is_empty() {
                    example.push_str(rule["example_preamble"].as_str().unwrap_or(""));
                    example.push('\n');
                    for ex in short_examples.iter().take(3) {
                        example.push_str(&format!("  > \"{}\"\n", ex));
                    }
                    example.push('\n');
                    example.push_str(rule["example_suggestion"].as_str().unwrap_or(""));
                }
            }
            Some("category_prompts") => {
                let cat = rule["example_category"].as_str().unwrap_or("");
                let max_count = rule["example_max_count"].as_u64().unwrap_or(3) as usize;
                let cat_examples = find_example_prompts(prompts, cat, max_count, 150);
                if !cat_examples.is_empty() {
                    example.push_str(rule["example_preamble"].as_str().unwrap_or(""));
                    example.push('\n');
                    for ex in cat_examples.iter().take(max_count) {
                        example.push_str(&format!("  > \"{}\"\n", ex));
                    }
                    example.push('\n');
                    example.push_str(rule["example_suggestion"].as_str().unwrap_or(""));
                }
            }
            _ => {}
        }

        if example.is_empty() {
            example = rule["fallback_example"].as_str().unwrap_or("").to_string();
        }

        recs.push(Recommendation {
            title: rule["title"].as_str().unwrap_or("").to_string(),
            severity,
            body,
            metric,
            example,
            rec_source: String::new(),
        });
    }

    recs
}

pub fn get_ai_recommendations(data: &ParseResult) -> Result<Vec<Recommendation>, String> {
    let api_key = std::env::var("ANTHROPIC_API_KEY")
        .map_err(|_| "ANTHROPIC_API_KEY not set".to_string())?;

    let analysis = &data.analysis;
    let summary = &data.dashboard.summary;
    let prompts = &data.prompts;
    let models = &data.models;
    let subagents = &data.subagents;
    let context_efficiency = &data.context_efficiency;
    let branches = &data.branches;
    let permission_modes = &data.permission_modes;
    let work_days = &data.work_days;

    // Build category summary
    let cat_summary = analysis.categories.iter()
        .take(8)
        .map(|c| format!("{}: {}%", c.cat, c.pct))
        .collect::<Vec<_>>()
        .join(", ");

    // Build length summary
    let len_summary = analysis.length_buckets.iter()
        .map(|l| format!("{}: {}%", l.bucket, l.pct))
        .collect::<Vec<_>>()
        .join(", ");

    // Sample prompts by category
    let prompts_sample: Vec<&Prompt> = prompts.iter().take(80).collect();
    let mut sample_by_cat: std::collections::HashMap<String, Vec<&Prompt>> = std::collections::HashMap::new();
    for p in &prompts_sample {
        let entry = sample_by_cat.entry(p.category.clone()).or_default();
        if entry.len() < 5 {
            entry.push(p);
        }
    }

    let mut sample_text = String::new();
    let mut cats_sorted: Vec<_> = sample_by_cat.iter().collect();
    cats_sorted.sort_by(|a, b| b.1.len().cmp(&a.1.len()));
    for (cat, samples) in &cats_sorted {
        sample_text.push_str(&format!("\n### {} ({} samples)\n", cat, samples.len()));
        for s in *samples {
            let text_trunc = if s.text.len() > 300 { &s.text[..300] } else { &s.text };
            sample_text.push_str(&format!("  [{}] ({}ch) \"{}\"\n", s.project, s.full_length, text_trunc));
        }
    }

    // Work pattern
    let work_summary = if work_days.is_empty() {
        "No work pattern data".to_string()
    } else {
        let total_active: f64 = work_days.iter().map(|d| d.active_hrs).sum();
        let avg_daily = total_active / work_days.len() as f64;
        let avg_prompts: f64 = work_days.iter().map(|d| d.prompts as f64).sum::<f64>() / work_days.len() as f64;
        format!(
            "Active days: {}, avg active hours/day: {:.1}h, avg prompts/day: {:.0}, total active hours: {:.1}h",
            work_days.len(), avg_daily, avg_prompts, total_active
        )
    };

    // Model usage
    let model_text = if models.is_empty() {
        "No model data".to_string()
    } else {
        models.iter()
            .filter(|m| m.msgs > 0)
            .map(|m| format!("  {}: {} msgs, ${:.2} estimated cost", m.display, m.msgs, m.estimated_cost))
            .collect::<Vec<_>>()
            .join("\n")
    };

    // Subagent usage
    let sa_text = if subagents.total_count > 0 {
        format!(
            "Total: {}, Compactions: {}\n  Types: {:?}\n  Subagent cost: ${:.2}",
            subagents.total_count,
            subagents.compaction_count,
            subagents.type_counts,
            subagents.estimated_cost,
        )
    } else {
        "No subagent data".to_string()
    };

    // Context efficiency
    let ce_text = format!(
        "Tool output: {}%, Conversation: {}%, Thinking blocks: {}, Subagent output share: {}%",
        context_efficiency.tool_pct,
        context_efficiency.conversation_pct,
        context_efficiency.thinking_blocks,
        context_efficiency.subagent_pct,
    );

    // Branch summary
    let branch_text = if branches.is_empty() {
        "No branch data".to_string()
    } else {
        branches.iter()
            .take(10)
            .map(|b| format!("  {}: {} msgs, {} sessions", b.branch, b.msgs, b.sessions))
            .collect::<Vec<_>>()
            .join("\n")
    };

    // Permission modes
    let pm_text = if permission_modes.is_empty() {
        "No permission data".to_string()
    } else {
        let total_pm: i64 = permission_modes.values().sum::<i64>().max(1);
        let mut entries: Vec<_> = permission_modes.iter()
            .map(|(k, v)| (k.clone(), *v))
            .collect();
        entries.sort_by(|a, b| b.1.cmp(&a.1));
        entries.iter()
            .map(|(k, v)| format!("{}: {} ({}%)", k, v, (*v as f64 / total_pm as f64 * 100.0).round() as i64))
            .collect::<Vec<_>>()
            .join(", ")
    };

    // Project quality
    let project_quality = serde_json::to_string_pretty(
        &analysis.project_quality.iter().take(8).collect::<Vec<_>>()
    ).unwrap_or_else(|_| "[]".to_string());

    let overview = format!(
        "- {} prompts across {} sessions, {} projects\n\
         - Date range: {} to {}\n\
         - Average prompt length: {} chars\n\
         - Estimated API cost: ${:.2}\n\
         - {}",
        analysis.total_prompts,
        summary.total_sessions,
        summary.unique_projects,
        summary.date_range_start,
        summary.date_range_end,
        analysis.avg_length,
        summary.estimated_cost,
        work_summary,
    );

    let prompt = AI_PROMPT_TEMPLATE
        .replace("{{overview}}", &overview)
        .replace("{{categories}}", &cat_summary)
        .replace("{{length_distribution}}", &len_summary)
        .replace("{{model_usage}}", &model_text)
        .replace("{{subagent_usage}}", &sa_text)
        .replace("{{context_efficiency}}", &ce_text)
        .replace("{{branch_activity}}", &branch_text)
        .replace("{{permission_modes}}", &pm_text)
        .replace("{{project_quality}}", &project_quality)
        .replace("{{sample_prompts}}", &sample_text);

    // Spinner in background thread
    let stop = Arc::new(AtomicBool::new(false));
    let stop_clone = Arc::clone(&stop);
    let spin_handle = thread::spawn(move || {
        let phases = [
            "Analyzing prompt patterns",
            "Evaluating model usage",
            "Reviewing session efficiency",
            "Checking workflow patterns",
            "Generating personalized tips",
        ];
        let chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
        let mut i: usize = 0;
        let t0 = Instant::now();
        while !stop_clone.load(Ordering::Relaxed) {
            let elapsed = t0.elapsed().as_secs() as usize;
            let phase_idx = (elapsed / 10).min(phases.len() - 1);
            print!("\r  {} {}... ({}s)", chars[i % chars.len()], phases[phase_idx], elapsed);
            let _ = std::io::stdout().flush();
            i += 1;
            thread::sleep(Duration::from_millis(100));
        }
        print!("\r{}\r", " ".repeat(60));
        let _ = std::io::stdout().flush();
    });

    // Make the API request
    let body = serde_json::json!({
        "model": "claude-opus-4-6",
        "max_tokens": 4000,
        "messages": [{"role": "user", "content": prompt}],
    });

    let result = ureq::post("https://api.anthropic.com/v1/messages")
        .set("x-api-key", &api_key)
        .set("anthropic-version", "2023-06-01")
        .set("content-type", "application/json")
        .send_json(body);

    stop.store(true, Ordering::Relaxed);
    let _ = spin_handle.join();

    let response = result.map_err(|e| format!("API request failed: {}", e))?;
    let resp_body: Value = response.into_json().map_err(|e| format!("Failed to parse response: {}", e))?;

    // Extract text from response
    let text = resp_body["content"]
        .as_array()
        .and_then(|arr| arr.first())
        .and_then(|block| block["text"].as_str())
        .ok_or_else(|| "No text content in API response".to_string())?
        .trim();

    // Parse JSON array from response
    let recs: Vec<Recommendation> = if text.starts_with('[') {
        serde_json::from_str(text).map_err(|e| format!("JSON parse error: {}", e))?
    } else {
        let start = text.find('[').ok_or("No JSON array found in response")?;
        let end = text.rfind(']').ok_or("No closing bracket in response")? + 1;
        serde_json::from_str(&text[start..end]).map_err(|e| format!("JSON parse error: {}", e))?
    };

    Ok(recs)
}

pub fn generate_recommendations(data: &ParseResult, use_api: bool) -> RecommendationsResult {
    let heuristic_recs = get_heuristic_recommendations(data);

    let mut tagged_heuristic: Vec<Recommendation> = heuristic_recs.into_iter().map(|mut r| {
        r.rec_source = "heuristic".to_string();
        r
    }).collect();

    if !use_api {
        println!("  Using heuristic analysis (--no-api)");
        return RecommendationsResult {
            recommendations: tagged_heuristic,
            source: "heuristic".to_string(),
        };
    }

    match get_ai_recommendations(data) {
        Ok(ai_recs) => {
            let mut tagged_ai: Vec<Recommendation> = ai_recs.into_iter().map(|mut r| {
                r.rec_source = "ai".to_string();
                r
            }).collect();

            let ai_count = tagged_ai.len();
            let heuristic_count = tagged_heuristic.len();
            tagged_ai.append(&mut tagged_heuristic);
            println!("  {} AI + {} heuristic = {} recommendations", ai_count, heuristic_count, tagged_ai.len());

            RecommendationsResult {
                recommendations: tagged_ai,
                source: "ai".to_string(),
            }
        }
        Err(error) => {
            println!("  AI analysis unavailable ({}), using heuristic analysis", error);
            RecommendationsResult {
                recommendations: tagged_heuristic,
                source: "heuristic".to_string(),
            }
        }
    }
}

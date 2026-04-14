use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use chrono::Local;

use crate::parser::{ParseResult, RecommendationsResult};

const TEMPLATE: &str = include_str!("template.html");

pub fn generate_html(data: &ParseResult, recommendations: &RecommendationsResult) -> String {
    // Build a combined payload matching the template's expected shape.
    // Since all our types derive Serialize, we construct a serde_json::Value
    // from the typed structs for template injection.
    let payload = serde_json::json!({
        "dashboard": data.dashboard,
        "drilldown": data.drilldown,
        "analysis": data.analysis,
        "recommendations": recommendations,
        "work_days": data.work_days,
        "models": data.models,
        "subagents": data.subagents,
        "branches": data.branches,
        "context_efficiency": data.context_efficiency,
        "versions": data.versions,
        "skills": data.skills,
        "slash_commands": data.slash_commands,
        "permission_modes": data.permission_modes,
        "config": data.config,
    });

    let payload_json = serde_json::to_string(&payload).unwrap_or_else(|_| "{}".to_string());
    TEMPLATE.replace("__DATA_PLACEHOLDER__", &payload_json)
}

pub fn write_report(html: &str, output_path: Option<&str>) -> Result<PathBuf, String> {
    let path = if let Some(p) = output_path {
        PathBuf::from(p)
    } else {
        let output_dir = std::env::current_dir()
            .map_err(|e| format!("Cannot get current dir: {}", e))?
            .join("output");
        fs::create_dir_all(&output_dir)
            .map_err(|e| format!("Cannot create output dir: {}", e))?;

        let timestamp = Local::now().format("%Y%m%d-%H%M%S").to_string();
        let filename = format!("claude-analytics-{}.html", timestamp);

        // Ensure output/ is gitignored
        ensure_gitignore(&output_dir);

        output_dir.join(filename)
    };

    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("Cannot create parent dir: {}", e))?;
    }

    fs::write(&path, html)
        .map_err(|e| format!("Cannot write report: {}", e))?;

    Ok(path)
}

pub fn read_last_run(output_dir: Option<&Path>) -> Option<String> {
    let dir = output_dir
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default().join("output"));
    let marker = dir.join(".last-run");
    if marker.exists() {
        if let Ok(content) = fs::read_to_string(&marker) {
            let content = content.trim();
            if content.len() >= 10 {
                return Some(content[..10].to_string());
            }
        }
    }
    None
}

pub fn save_last_run(output_dir: Option<&Path>) {
    let dir = output_dir
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_default().join("output"));
    let _ = fs::create_dir_all(&dir);
    let marker = dir.join(".last-run");
    let content = Local::now().format("%Y-%m-%d %H:%M:%S\n").to_string();
    let _ = fs::write(&marker, content);
}

fn ensure_gitignore(output_dir: &Path) {
    // .gitignore inside output/
    let inner_gitignore = output_dir.join(".gitignore");
    if !inner_gitignore.exists() {
        let _ = fs::write(
            &inner_gitignore,
            "# Claude Analytics reports contain sensitive session data.\n\
             # Do NOT commit these files to version control.\n\
             *\n\
             !.gitignore\n",
        );
    }

    // Add 'output/' to project root .gitignore
    if let Some(parent) = output_dir.parent() {
        let root_gitignore = parent.join(".gitignore");
        if root_gitignore.exists() {
            if let Ok(content) = fs::read_to_string(&root_gitignore) {
                if !content.contains("output/") {
                    let _ = fs::OpenOptions::new()
                        .append(true)
                        .open(&root_gitignore)
                        .and_then(|mut f| {
                            writeln!(f, "\n# Claude Analytics reports (contain sensitive data)\noutput/")
                        });
                }
            }
        } else {
            let _ = fs::write(
                &root_gitignore,
                "# Claude Analytics reports (contain sensitive data)\noutput/\n",
            );
        }
    }
}

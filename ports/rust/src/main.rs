mod analyzer;
mod generator;
mod parser;

use std::path::PathBuf;
use std::process::Command;

use clap::Parser;

const VERSION: &str = "0.1.0";

const ORANGE: &str = "\x1b[38;2;227;115;34m";
const RESET: &str = "\x1b[0m";

const BANNER_LINES: &[&str] = &[
    "   ____ _                 _",
    "  / ___| | __ _ _   _  __| | ___",
    " | |   | |/ _` | | | |/ _` |/ _ \\",
    " | |___| | (_| | |_| | (_| |  __/",
    "  \\____|_|\\__,_|\\__,_|\\__,_|\\___|",
    "     _                _       _   _",
    "    / \\   _ __   __ _| |_   _| |_(_) ___ ___",
    "   / _ \\ | '_ \\ / _` | | | | | __| |/ __/ __|",
    "  / ___ \\| | | | (_| | | |_| | |_| | (__\\__ \\",
    " /_/   \\_\\_| |_|\\__,_|_|\\__, |\\__|_|\\___|___/",
    "                         |___/",
];

#[derive(Parser, Debug)]
#[command(name = "claude-analytics")]
#[command(about = "Analyze your Claude Code usage and level up your prompting.")]
#[command(version = VERSION)]
struct Cli {
    /// Skip AI-powered analysis (no API key needed)
    #[arg(long)]
    no_api: bool,

    /// Don't auto-open the report in the browser
    #[arg(long)]
    no_open: bool,

    /// Output path for the HTML report
    #[arg(short, long)]
    output: Option<String>,

    /// Path to .claude directory (default: ~/.claude)
    #[arg(long)]
    claude_dir: Option<String>,

    /// Timezone offset from UTC in hours (auto-detected if not set)
    #[arg(long)]
    tz_offset: Option<i32>,

    /// Only include data since this date (YYYY-MM-DD) or 'last' for since last run
    #[arg(long)]
    since: Option<String>,
}

fn open_in_browser(filepath: &PathBuf) {
    let path = filepath.to_string_lossy().to_string();
    if cfg!(target_os = "macos") {
        let _ = Command::new("open").arg(&path).spawn();
    } else if cfg!(target_os = "linux") {
        let _ = Command::new("xdg-open").arg(&path).spawn();
    } else if cfg!(target_os = "windows") {
        let _ = Command::new("cmd").args(["/C", "start", &path]).spawn();
    } else {
        let _ = Command::new("open").arg(&path).spawn();
    }
}

fn main() {
    // Load .env from project root (two levels up from ports/rust/)
    let exe_dir = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf()));
    let cwd = std::env::current_dir().ok();
    for dir in [exe_dir.as_ref().map(|d| d.join("../../.env")),
                cwd.as_ref().map(|d| d.join(".env"))]
        .into_iter().flatten() {
        if dir.exists() {
            let _ = dotenv::from_path(&dir);
            break;
        }
    }

    let cli = Cli::parse();

    // Print banner
    println!();
    for line in BANNER_LINES {
        println!("{}{}{}", ORANGE, line, RESET);
    }
    println!();
    println!("  v{}", VERSION);
    println!();

    // Step 1: Find Claude directory
    println!("{}[1/5]{} Locating Claude data...", ORANGE, RESET);
    let claude_dir = if let Some(ref dir) = cli.claude_dir {
        let p = PathBuf::from(dir);
        if !p.exists() {
            eprintln!("  Error: {} not found", dir);
            std::process::exit(1);
        }
        p
    } else {
        match parser::find_claude_dir() {
            Ok(p) => p,
            Err(e) => {
                eprintln!("  Error: {}", e);
                std::process::exit(1);
            }
        }
    };
    println!("  Found: {}", claude_dir.display());

    // Resolve --since flag
    let since_date: Option<String> = if let Some(ref since) = cli.since {
        if since.to_lowercase() == "last" {
            let last = generator::read_last_run(None);
            if let Some(ref d) = last {
                println!("  Filtering to data since last run: {}", d);
            } else {
                println!("  No previous run found, showing all data");
            }
            last
        } else {
            println!("  Filtering to data since: {}", since);
            Some(since.clone())
        }
    } else {
        None
    };

    // Step 2: Parse sessions
    println!("{}[2/5]{} Parsing sessions...", ORANGE, RESET);
    let data = match parser::parse_all_sessions(&claude_dir, cli.tz_offset, since_date.as_deref()) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("  Error: {}", e);
            std::process::exit(1);
        }
    };

    let summary = &data.dashboard.summary;
    let total_sessions = summary.total_sessions;
    let unique_projects = summary.unique_projects;
    let total_user_msgs = summary.total_user_msgs;
    let total_prompts = data.analysis.total_prompts;
    let date_start = &summary.date_range_start;
    let date_end = &summary.date_range_end;
    let tz_label = &summary.tz_label;

    println!("  {} sessions across {} projects", total_sessions, unique_projects);
    println!("  {} messages, {} prompts", total_user_msgs, total_prompts);
    if since_date.is_some() {
        println!("  Showing: {} -> {}", since_date.as_deref().unwrap_or(""), date_end);
    } else {
        println!("  {} -> {}", date_start, date_end);
    }
    println!("  Timezone: {}", tz_label);

    // Step 3: Analysis
    println!("{}[3/5]{} Analyzing prompt patterns...", ORANGE, RESET);
    let use_api = !cli.no_api;
    if use_api {
        println!("  AI-powered analysis enabled (use --no-api to skip)");
    } else {
        println!("  Using heuristic analysis (--no-api)");
    }

    // Step 4: Generate recommendations
    if use_api {
        println!("{}[4/5]{} Generating AI-powered recommendations...", ORANGE, RESET);
    } else {
        println!("{}[4/5]{} Generating heuristic recommendations...", ORANGE, RESET);
    }
    let recommendations = analyzer::generate_recommendations(&data, use_api);
    let rec_count = recommendations.recommendations.len();
    let source = &recommendations.source;
    if source != "ai" && !cli.no_api {
        // AI was attempted but failed; count already printed by generate_recommendations
    }
    println!("  {} total recommendations ({})", rec_count, source);

    // Step 5: Generate report
    println!("{}[5/5]{} Generating report...", ORANGE, RESET);
    let html = generator::generate_html(&data, &recommendations);
    let output_path = match generator::write_report(&html, cli.output.as_deref()) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("  Error: {}", e);
            std::process::exit(1);
        }
    };
    println!("  Report saved to: {}", output_path.display());

    if let Ok(meta) = std::fs::metadata(&output_path) {
        let size_kb = meta.len() as f64 / 1024.0;
        println!("  Size: {:.0} KB", size_kb);
    }

    // Save the last-run marker
    generator::save_last_run(None);
    println!();

    // Open in browser
    if !cli.no_open {
        println!("Opening report in browser...");
        open_in_browser(&output_path);
    } else {
        println!("Open the report: file://{}", output_path.display());
    }

    println!();
    println!("Done! Go level up your Claude game.");
}

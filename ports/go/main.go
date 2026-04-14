package main

import (
	"bufio"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

const version = "0.1.0"

var bannerLines = []string{
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
}

const (
	orange = "\033[38;2;227;115;34m"
	reset  = "\033[0m"
)

func printBanner() {
	fmt.Println()
	for _, line := range bannerLines {
		fmt.Printf("%s%s%s\n", orange, line, reset)
	}
	fmt.Println()
	fmt.Printf("  v%s\n", version)
	fmt.Println()
}

func loadEnvFile() {
	// Load .env from project root (two levels up from ports/go/)
	exe, err := os.Executable()
	if err != nil {
		return
	}
	// Try relative to executable, then relative to cwd
	paths := []string{
		filepath.Join(filepath.Dir(exe), "..", "..", ".env"),
		filepath.Join(filepath.Dir(exe), ".env"),
	}
	if wd, err := os.Getwd(); err == nil {
		paths = append(paths, filepath.Join(wd, ".env"))
	}
	for _, p := range paths {
		f, err := os.Open(p)
		if err != nil {
			continue
		}
		scanner := bufio.NewScanner(f)
		for scanner.Scan() {
			line := strings.TrimSpace(scanner.Text())
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			parts := strings.SplitN(line, "=", 2)
			if len(parts) != 2 {
				continue
			}
			key := strings.TrimSpace(parts[0])
			val := strings.TrimSpace(parts[1])
			// Strip surrounding quotes
			if len(val) >= 2 && ((val[0] == '"' && val[len(val)-1] == '"') || (val[0] == '\'' && val[len(val)-1] == '\'')) {
				val = val[1 : len(val)-1]
			}
			// Only set if not already in environment
			if os.Getenv(key) == "" {
				os.Setenv(key, val)
			}
		}
		f.Close()
		break // stop after first found
	}
}

func openInBrowser(fpath string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", fpath)
	case "linux":
		cmd = exec.Command("xdg-open", fpath)
	case "windows":
		cmd = exec.Command("cmd", "/c", "start", fpath)
	default:
		cmd = exec.Command("open", fpath)
	}
	cmd.Run()
}

func main() {
	showVersion := flag.Bool("version", false, "Show version and exit")
	noAPI := flag.Bool("no-api", false, "Skip AI-powered analysis (no API key needed)")
	noOpen := flag.Bool("no-open", false, "Don't auto-open the report in the browser")
	output := flag.String("output", "", "Output path for the HTML report")
	claudeDir := flag.String("claude-dir", "", "Path to .claude directory (default: ~/.claude)")
	tzOffset := flag.Int("tz-offset", -999, "Timezone offset from UTC in hours (auto-detected if not set)")
	since := flag.String("since", "", "Only include data since this date (YYYY-MM-DD) or 'last' for since last run")

	flag.Parse()

	if *showVersion {
		fmt.Printf("claude-analytics %s\n", version)
		os.Exit(0)
	}

	// Load .env for ANTHROPIC_API_KEY
	loadEnvFile()

	useAPI := !*noAPI && os.Getenv("ANTHROPIC_API_KEY") != ""

	printBanner()

	// Step 1: Find Claude directory
	fmt.Printf("%s[1/5]%s Locating Claude data...\n", orange, reset)
	var dir string
	if *claudeDir != "" {
		if _, err := os.Stat(*claudeDir); os.IsNotExist(err) {
			fmt.Printf("  Error: %s not found\n", *claudeDir)
			os.Exit(1)
		}
		dir = *claudeDir
	} else {
		var err error
		dir, err = FindClaudeDir()
		if err != nil {
			fmt.Printf("  Error: %s\n", err)
			os.Exit(1)
		}
	}
	fmt.Printf("  Found: %s\n", dir)

	// Resolve --since flag
	sinceDate := ""
	if *since != "" {
		if *since == "last" {
			sinceDate = ReadLastRun()
			if sinceDate != "" {
				fmt.Printf("  Filtering to data since last run: %s\n", sinceDate)
			} else {
				fmt.Println("  No previous run found, showing all data")
			}
		} else {
			sinceDate = *since
			fmt.Printf("  Filtering to data since: %s\n", sinceDate)
		}
	}

	// Step 2: Parse sessions
	fmt.Printf("%s[2/5]%s Parsing sessions...\n", orange, reset)
	var tzPtr *int
	if *tzOffset != -999 {
		tzPtr = tzOffset
	}
	data, err := ParseAllSessions(dir, tzPtr, sinceDate)
	if err != nil {
		fmt.Printf("  Error: %s\n", err)
		os.Exit(1)
	}

	summary := data.Dashboard.Summary
	fmt.Printf("  %d sessions across %d projects\n", summary.TotalSessions, summary.UniqueProjects)
	fmt.Printf("  %d messages, %d prompts\n", summary.TotalUserMsgs, data.Analysis.TotalPrompts)
	if sinceDate != "" {
		fmt.Printf("  Showing: %s -> %s\n", sinceDate, summary.DateRangeEnd)
	} else {
		fmt.Printf("  %s -> %s\n", summary.DateRangeStart, summary.DateRangeEnd)
	}
	fmt.Printf("  Timezone: %s\n", summary.TzLabel)

	// Step 3: Analyze
	fmt.Printf("%s[3/5]%s Analyzing prompt patterns...\n", orange, reset)
	if useAPI {
		fmt.Println("  API key found - will use AI-powered analysis")
	} else {
		if *noAPI {
			fmt.Println("  Using heuristic analysis (--no-api)")
		} else {
			fmt.Println("  No ANTHROPIC_API_KEY found, using heuristic analysis")
		}
	}

	// Step 4: Generate recommendations
	if useAPI {
		fmt.Printf("%s[4/5]%s Generating AI-powered recommendations...\n", orange, reset)
	} else {
		fmt.Printf("%s[4/5]%s Generating heuristic recommendations...\n", orange, reset)
	}
	recommendations := GenerateRecommendations(data, useAPI)
	recCount := len(recommendations.Recommendations)
	fmt.Printf("  %d recommendations (%s)\n", recCount, recommendations.Source)

	// Step 5: Generate report
	fmt.Printf("%s[5/5]%s Generating report...\n", orange, reset)
	html := GenerateHTML(data, recommendations)
	outputPath, err := WriteReport(html, *output)
	if err != nil {
		fmt.Printf("  Error writing report: %s\n", err)
		os.Exit(1)
	}
	fmt.Printf("  Report saved to: %s\n", outputPath)

	info, err := os.Stat(outputPath)
	if err == nil {
		fileSizeKB := float64(info.Size()) / 1024
		fmt.Printf("  Size: %.0f KB\n", fileSizeKB)
	}

	// Save the last-run marker
	SaveLastRun()
	fmt.Println()

	// Open in browser
	if !*noOpen {
		fmt.Println("Opening report in browser...")
		openInBrowser(outputPath)
	} else {
		fmt.Printf("Open the report: file://%s\n", outputPath)
	}

	fmt.Println()
	fmt.Println("Done! Go level up your Claude game.")
}

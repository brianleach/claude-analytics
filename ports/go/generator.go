package main

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

//go:embed template.html
var templateHTML string

// Payload is the data structure injected into the template.
type Payload struct {
	Dashboard         interface{} `json:"dashboard"`
	Drilldown         interface{} `json:"drilldown"`
	Analysis          interface{} `json:"analysis"`
	Recommendations   interface{} `json:"recommendations"`
	WorkDays          interface{} `json:"work_days"`
	Models            interface{} `json:"models"`
	Subagents         interface{} `json:"subagents"`
	Branches          interface{} `json:"branches"`
	ContextEfficiency interface{} `json:"context_efficiency"`
	Versions          interface{} `json:"versions"`
	Skills            interface{} `json:"skills"`
	SlashCommands     interface{} `json:"slash_commands"`
	Config            interface{} `json:"config"`
}

// GenerateHTML generates the final HTML dashboard.
func GenerateHTML(data *ParseResult, recommendations RecommendationResult) string {
	payload := Payload{
		Dashboard:         data.Dashboard,
		Drilldown:         data.Drilldown,
		Analysis:          data.Analysis,
		Recommendations:   recommendations,
		WorkDays:          data.WorkDays,
		Models:            data.Models,
		Subagents:         data.Subagents,
		Branches:          data.Branches,
		ContextEfficiency: data.ContextEfficiency,
		Versions:          data.Versions,
		Skills:            data.Skills,
		SlashCommands:     data.SlashCommands,
		Config:            data.Config,
	}

	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		payloadJSON = []byte("{}")
	}

	html := strings.Replace(templateHTML, "__DATA_PLACEHOLDER__", string(payloadJSON), 1)
	return html
}

// WriteReport writes the HTML report to disk.
func WriteReport(html string, outputPath string) (string, error) {
	if outputPath == "" {
		cwd, err := os.Getwd()
		if err != nil {
			return "", err
		}
		outputDir := filepath.Join(cwd, "output")
		if err := os.MkdirAll(outputDir, 0o755); err != nil {
			return "", err
		}
		timestamp := time.Now().Format("20060102-150405")
		outputPath = filepath.Join(outputDir, fmt.Sprintf("claude-analytics-%s.html", timestamp))
		ensureGitignore(outputDir)
	}

	dir := filepath.Dir(outputPath)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}

	if err := os.WriteFile(outputPath, []byte(html), 0o644); err != nil {
		return "", err
	}

	return outputPath, nil
}

// ReadLastRun reads the last run timestamp from the .last-run marker file.
func ReadLastRun() string {
	cwd, err := os.Getwd()
	if err != nil {
		return ""
	}
	marker := filepath.Join(cwd, "output", ".last-run")
	data, err := os.ReadFile(marker)
	if err != nil {
		return ""
	}
	content := strings.TrimSpace(string(data))
	if len(content) >= 10 {
		return content[:10]
	}
	return ""
}

// SaveLastRun saves the current timestamp as the last run marker.
func SaveLastRun() {
	cwd, err := os.Getwd()
	if err != nil {
		return
	}
	outputDir := filepath.Join(cwd, "output")
	os.MkdirAll(outputDir, 0o755)
	marker := filepath.Join(outputDir, ".last-run")
	content := time.Now().Format("2006-01-02 15:04:05") + "\n"
	os.WriteFile(marker, []byte(content), 0o644)
}

func ensureGitignore(outputDir string) {
	// .gitignore inside output/
	innerGitignore := filepath.Join(outputDir, ".gitignore")
	if _, err := os.Stat(innerGitignore); os.IsNotExist(err) {
		content := "# Claude Analytics reports contain sensitive session data.\n" +
			"# Do NOT commit these files to version control.\n" +
			"*\n" +
			"!.gitignore\n"
		os.WriteFile(innerGitignore, []byte(content), 0o644)
	}

	// Also add 'output/' to the project root .gitignore
	rootGitignore := filepath.Join(filepath.Dir(outputDir), ".gitignore")
	data, err := os.ReadFile(rootGitignore)
	if err == nil {
		if !strings.Contains(string(data), "output/") {
			f, err := os.OpenFile(rootGitignore, os.O_APPEND|os.O_WRONLY, 0o644)
			if err == nil {
				f.WriteString("\n# Claude Analytics reports (contain sensitive data)\noutput/\n")
				f.Close()
			}
		}
	} else if os.IsNotExist(err) {
		os.WriteFile(rootGitignore, []byte("# Claude Analytics reports (contain sensitive data)\noutput/\n"), 0o644)
	}
}

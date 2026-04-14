.PHONY: install run run-no-api benchmark test

VENV := .venv
PYTHON := $(VENV)/bin/python

# Default: install Python port with AI support
install:
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -e "ports/python[ai]"

# Run the Python port (primary, with AI recommendations)
run:
	$(PYTHON) -m claude_analytics

# Run without AI (no API key needed)
run-no-api:
	$(PYTHON) -m claude_analytics --no-api

# Run tests
test:
	$(PYTHON) -m unittest discover ports/python/tests/ -v

# Benchmark all ports
benchmark:
	./benchmark.sh

# Sync shared template to Go (go:embed can't follow symlinks)
sync-templates:
	cp shared/template.html ports/go/template.html

# Individual ports
run-ts:
	cd ports/typescript && npx ts-node src/cli.ts

run-go:
	cd ports/go && go run .

run-rust:
	cd ports/rust && cargo run --release

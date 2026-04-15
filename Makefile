.PHONY: install run run-no-api benchmark test

VENV := .venv
PYTHON := $(VENV)/bin/python

# Install all ports
install:
	cd ports/typescript && npm install --silent
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -e "ports/python[ai]"

# Run a port: make run [PORT=ts|python|go|rust]
PORT ?= ts
run:
ifeq ($(PORT),python)
	$(PYTHON) -m claude_analytics
else ifeq ($(PORT),ts)
	cd ports/typescript && npx ts-node src/cli.ts
else ifeq ($(PORT),go)
	cp shared/ai_prompt.txt shared/template.html shared/heuristic_rules.json ports/go/
	cd ports/go && go run .
else ifeq ($(PORT),rust)
	cd ports/rust && cargo run --release
else
	@echo "Unknown port: $(PORT). Use python, ts, go, or rust."
	@exit 1
endif

# Run without AI (no API key needed)
PORT_NOAPI ?= ts
run-no-api:
ifeq ($(PORT_NOAPI),python)
	$(PYTHON) -m claude_analytics --no-api
else ifeq ($(PORT_NOAPI),ts)
	cd ports/typescript && npx ts-node src/cli.ts --no-api
else ifeq ($(PORT_NOAPI),go)
	cp shared/ai_prompt.txt shared/template.html shared/heuristic_rules.json ports/go/
	cd ports/go && go run . -no-api
else ifeq ($(PORT_NOAPI),rust)
	cd ports/rust && cargo run --release -- --no-api
else
	@echo "Unknown port: $(PORT_NOAPI). Use python, ts, go, or rust."
	@exit 1
endif

# Run tests
test:
	$(PYTHON) -m unittest discover ports/python/tests/ -v

# Benchmark all ports
benchmark:
	./benchmark.sh



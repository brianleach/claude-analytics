.PHONY: install run run-no-api benchmark test

# Default: install Python port with AI support
install:
	cd ports/python && pip install -e ".[ai]"

# Run the Python port (primary, with AI recommendations)
run:
	cd ports/python && python -m claude_analytics

# Run without AI (no API key needed)
run-no-api:
	cd ports/python && python -m claude_analytics --no-api

# Run tests
test:
	cd ports/python && python -m unittest discover tests/ -v

# Benchmark all ports
benchmark:
	./benchmark.sh

# Individual ports
run-ts:
	cd ports/typescript && npx ts-node src/cli.ts

run-go:
	cd ports/go && go run .

run-rust:
	cd ports/rust && cargo run --release

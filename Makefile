.PHONY: install install-dev test lint format check docker-build clean

# Install the package (production dependencies only)
install:
	pip install -e .

# Install with dev dependencies (test + lint)
install-dev:
	pip install -e ".[dev]"

# Run the test suite
test:
	pytest

# Lint all source and test files
lint:
	ruff check repomind tests

# Auto-fix lint issues
format:
	ruff check --fix repomind tests

# Lint + test in one shot (used in CI)
check: lint test

# Build the Docker image
docker-build:
	docker build -t repomind:latest .

# Remove build artifacts
clean:
	rm -rf dist build *.egg-info __pycache__ .pytest_cache .ruff_cache

.PHONY: help install test build clean
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "%-10s %s\n", $$1, $$2}'

install: ## Sync dependencies from uv.lock
	uv sync --locked

test: ## Run the test suite
	uv run pytest tests/ -q

build: ## Build sdist and wheel
	uv build

clean: ## Remove build artifacts, caches, and the venv
	rm -rf output/ dist/ .pytest_cache .venv
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

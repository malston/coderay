.PHONY: help install install-global uninstall test build clean
.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[^:]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "%-10s %s\n", $$1, $$2}'

install: ## Sync dependencies from uv.lock
	uv sync --locked

install-global: ## Install the crack CLI onto your PATH via uv tool
	uv tool install --editable .

uninstall: ## Uninstall the crack CLI
	uv tool uninstall crack

test: ## Run the test suite
	uv run pytest tests/ -q

build: ## Build sdist and wheel
	uv build

clean: ## Remove build artifacts, caches, and the venv
	rm -rf output/ dist/ .pytest_cache .venv
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

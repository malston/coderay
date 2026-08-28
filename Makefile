.PHONY: install test build clean

install:
	uv sync --locked

test:
	uv run pytest tests/ -q

build:
	uv build

clean:
	rm -rf output/ dist/ .pytest_cache .venv
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

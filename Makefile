.PHONY: format format-check lint check

format:
	cargo fmt --all
	uv run ruff format src/solidrecipe-core/python examples
	pnpm -C src/solidrecipe-viewer format

format-check:
	cargo fmt --all -- --check
	uv run ruff format --check src/solidrecipe-core/python examples
	pnpm -C src/solidrecipe-viewer format:check

lint:
	cargo clippy --workspace --all-targets -- -D warnings
	uv run ruff check src/solidrecipe-core/python examples
	pnpm -C src/solidrecipe-viewer lint

check: format-check lint
	cargo test --workspace
	pnpm -C src/solidrecipe-viewer build

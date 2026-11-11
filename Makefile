.PHONY: build viewer-build format format-check lint check

# Cargo embeds the production viewer; build its assets before compiling the CLI.
viewer-build:
	pnpm -C src/solidrecipe-viewer build

build: viewer-build
	cargo build --release --workspace

format:
	cargo fmt --all
	uv run ruff format src/solidrecipe-core/python examples tests
	pnpm -C src/solidrecipe-viewer format

format-check:
	cargo fmt --all -- --check
	uv run ruff format --check src/solidrecipe-core/python examples tests
	pnpm -C src/solidrecipe-viewer format:check

lint: viewer-build
	cargo clippy --workspace --all-targets -- -D warnings
	uv run ruff check src/solidrecipe-core/python examples tests
	pnpm -C src/solidrecipe-viewer lint

check: format-check lint
	cargo build --workspace
	cargo test --workspace
	uv run python -m unittest discover -s tests

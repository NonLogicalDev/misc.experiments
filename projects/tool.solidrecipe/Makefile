.PHONY: build viewer-build prepare-solidcore format format-check lint check
export RUFF_CACHE_DIR := $(CURDIR)/.work/cache/ruff

# Compose the pinned dependency and SolidRecipe patches without changing the submodule.
prepare-solidcore:
	./scripts/prepare-solidcraft.sh

# Cargo embeds the production viewer; build its assets before compiling the CLI.
viewer-build:
	pnpm -C src/solidrecipe-viewer build

build: prepare-solidcore viewer-build
	cd src && cargo build --release --workspace

format:
	cd src && cargo fmt -p solidrecipe-core -p solidrecipe
	uv run --project src/solidrecipe-core ruff format --config src/solidrecipe-core/pyproject.toml src/solidrecipe-core/python examples tests
	pnpm -C src/solidrecipe-viewer format

format-check:
	cd src && cargo fmt -p solidrecipe-core -p solidrecipe -- --check
	uv run --project src/solidrecipe-core ruff format --check --config src/solidrecipe-core/pyproject.toml src/solidrecipe-core/python examples tests
	pnpm -C src/solidrecipe-viewer format:check

lint: prepare-solidcore viewer-build
	cd src && cargo clippy --workspace --all-targets -- -D warnings
	uv run --project src/solidrecipe-core ruff check --config src/solidrecipe-core/pyproject.toml src/solidrecipe-core/python examples tests
	pnpm -C src/solidrecipe-viewer lint

check: prepare-solidcore format-check lint
	cd src && cargo build --workspace
	cd src && cargo test --workspace
	uv run --project src/solidrecipe-core python -m unittest discover -s tests

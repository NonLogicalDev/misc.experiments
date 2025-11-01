default:
    @just --list

save:
    git add -A
    git commit -m "$(date) :: save"

git-sanitize:
    uv run scripts/clean-repo.py --force

git-sanitize-commit:
    uv run scripts/clean-repo.py --force
default:
    @just --list

save:
    git add -A
    git commit -m "$(date) :: save"

git-sanitize:
    uv run scripts/clean-repo.py --force

git-sanitize-commit:
    uv run scripts/clean-repo.py --force

git-configure:
    git remote add origin git@github.com:NonLogicalDev/misc.experiments
    git fetch origin
    git branch --set-upstream-to=origin/main main
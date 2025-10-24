#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "git-filter-repo",
# ]
# ///

import sys
import subprocess
import argparse
import git_filter_repo as gfr
from dataclasses import dataclass

AUTHOR_EMAIL = "hello@nonlogical.io"
AUTHOR_NAME = "Nonlogical"

@dataclass
class RepoFilter():
  def commit_callback(self, commit, metadata):
    # Update author information
    commit.author_name = AUTHOR_NAME.encode('utf-8')
    commit.author_email = AUTHOR_EMAIL.encode('utf-8')
    commit.committer_name = AUTHOR_NAME.encode('utf-8')
    commit.committer_email = AUTHOR_EMAIL.encode('utf-8')


def main():
  args = argparse.ArgumentParser()
  args.add_argument('--force', action='store_true', help='Force the commit')
  args.add_argument('--dry-run', action='store_true', help='Dry run the commit')
  args.parse_args()

  repo_filter = RepoFilter()
  repo_filter_args = []
  if args.force:
    repo_filter_args.append('--force')
  if args.dry_run:
    repo_filter_args.append('--dry-run')
  filter_args = gfr.FilteringOptions.parse_args(repo_filter_args, error_on_empty = False)
  filter = gfr.RepoFilter(filter_args, commit_callback=repo_filter.commit_callback)
  filter.run()


if __name__ == '__main__':
  main()

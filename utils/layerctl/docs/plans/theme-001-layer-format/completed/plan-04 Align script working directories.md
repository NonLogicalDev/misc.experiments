# Align script working directories

## Goal

Run both `operation.script` and `git-clone.pre-checkout-script` with the composed workspace root as their current directory. The clone hook must continue to operate on its temporary bare repository and private index through `GIT_DIR` and `GIT_INDEX_FILE`, before source files are materialized. Also expose `LAYERCTL_GITCLONE_BARE_DIR` and `LAYERCTL_GITCLONE_INDEX_FILE` without removing existing variables. [Owners](../../OWNERS.md).

## Work

- [x] Change the clone hook working directory while preserving bare Git context and existing script operation behavior.
- [x] Verify the working directory, Git context, and absence of clone files during the hook; run the Go suite and replay the Deluge composition.
- [x] Update documentation and the layerctl skill; save the verified changes locally.

The complete Go suite and layerctl skill validation passed. A case-insensitive Deluge projection and `check` replay produced the recorded firmware tree. The focused test confirms the workspace is the current directory, source files are not materialized yet, Git targets a bare repository and private index, and both clone-specific environment paths match Git’s variables.

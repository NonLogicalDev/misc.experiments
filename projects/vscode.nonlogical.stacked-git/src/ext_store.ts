import * as vscode from "vscode";
import {
  StgPatchName,
  GitSHA,
  GitFileStatus,
  StgPatchStats,
  StgStackMeta,
} from "./ext_model";
import { globalContext } from "./ext_context";

/**
 * Store for managing Stacked Git extension state and data
 */
export class StackedGitExtensionStore {
  public d_sig_updated = new vscode.EventEmitter<void>();
  public d_stack_sha?: GitSHA = undefined;
  public d_branch?: string = undefined; // Add branch storage

  public d_patch_names = new Set<StgPatchName>();

  public d_patch_0_applied = new Array<StgPatchName>();
  public d_patch_1_unapplied = new Array<StgPatchName>();
  public d_patch_2_hidden = new Array<StgPatchName>();

  public d_patch_shas = new Map<StgPatchName, GitSHA>();
  public d_patch_subjects = new Map<StgPatchName, string>();
  public d_patch_messages = new Map<StgPatchName, string>();
  public d_patch_stats = new Map<StgPatchName, StgPatchStats>();
  public d_patch_ts = new Map<StgPatchName, number>();
  public d_patch_files = new Map<StgPatchName, GitFileStatus[]>();

  constructor(public rootPath: string) {}

  async reload() {
    try {
      // Get current git branch and store it
      this.d_branch = await globalContext.apiGitCurrentBranch({
        rootPath: this.rootPath,
      });

      const stgMetaJsonRef = `refs/stacks/${this.d_branch}:stack.json`;

      // Fetch the sha of the ref
      const stackSha = await globalContext.apiGitRevParse({
        ref: stgMetaJsonRef,
        rootPath: this.rootPath,
      });

      // Only proceed with full refresh if the SHA has changed
      if (stackSha !== this.d_stack_sha) {
        this.d_stack_sha = stackSha;

        // Fetch STG Stack Metadata JSON.
        const stgMetaJson = await globalContext.apiGitCatFile({
          ref: stgMetaJsonRef,
          rootPath: this.rootPath,
        });

        // And parse it.
        const stgMeta: StgStackMeta = JSON.parse(stgMetaJson);

        // Clear existing data
        this.d_patch_names.clear();
        this.d_patch_shas.clear();
        this.d_patch_stats.clear();

        // Add all patches to the set and store their SHAs
        this.d_patch_0_applied = [];
        for (const patchName of stgMeta.applied) {
          this.d_patch_names.add(patchName);
          this.d_patch_0_applied.push(patchName);
          this.d_patch_stats.set(patchName, { linesAdded: 0, linesRemoved: 0 });
          if (stgMeta.patches[patchName]) {
            this.d_patch_shas.set(patchName, stgMeta.patches[patchName].oid);
          }
        }

        this.d_patch_1_unapplied = [];
        for (const patchName of stgMeta.unapplied) {
          this.d_patch_names.add(patchName);
          this.d_patch_1_unapplied.push(patchName);
          this.d_patch_stats.set(patchName, { linesAdded: 0, linesRemoved: 0 });
          if (stgMeta.patches[patchName]) {
            this.d_patch_shas.set(patchName, stgMeta.patches[patchName].oid);
          }
        }

        this.d_patch_2_hidden = [];
        for (const patchName of stgMeta.hidden) {
          this.d_patch_names.add(patchName);
          this.d_patch_2_hidden.push(patchName);
          this.d_patch_stats.set(patchName, { linesAdded: 0, linesRemoved: 0 });
          if (stgMeta.patches[patchName]) {
            this.d_patch_shas.set(patchName, stgMeta.patches[patchName].oid);
          }
        }

        // Get commit message bodies and timestamps for all patches.
        await Promise.all(
          Array.from(this.d_patch_shas).map(async ([patchName, sha]) => {
            try {
              // Get commit message body, timestamp and status in parallel
              const [messageBody, timestamp, statusOutput, numstats] =
                await Promise.all([
                  globalContext.apiGitLog({
                    sha,
                    format: "%B",
                    rootPath: this.rootPath,
                  }),
                  globalContext.apiGitLog({
                    sha,
                    format: "%ct",
                    rootPath: this.rootPath,
                  }),
                  globalContext.apiGitShowNameStatus({
                    sha,
                    rootPath: this.rootPath,
                  }),
                  globalContext.apiGitShowNumstat({
                    sha,
                    rootPath: this.rootPath,
                  }),
                ]);

              // Parse status output into modified/deleted/moved files
              const fileStatuses = new Map<string, GitFileStatus>();

              const fileStats = new Map<
                string,
                {
                  linesAdded: number;
                  linesRemoved: number;
                }
              >();

              for (const line of numstats.trim().split("\n")) {
                if (!line) {
                  continue;
                }
                const [added, removed, path] = line.split("\t");
                fileStats.set(path, {
                  linesAdded: parseInt(added) || 0,
                  linesRemoved: parseInt(removed) || 0,
                });
              }

              for (const line of statusOutput.trim().split("\n")) {
                if (!line) {
                  continue;
                }
                const [status, pathInfo] = line.split("\t");
                console.log(patchName, status, line);

                if (status === "D" || status === "M" || status === "A") {
                  const path = pathInfo;
                  const stats = fileStats.get(path) || {
                    linesAdded: 0,
                    linesRemoved: 0,
                  };
                  fileStatuses.set(path, {
                    status: status,
                    oldPath: path,
                    newPath: path,
                    linesAdded: stats.linesAdded,
                    linesRemoved: stats.linesRemoved,
                  });
                } else if (status.startsWith("R")) {
                  const [oldPath, newPath] = pathInfo.split(" -> ");
                  const stats = fileStats.get(newPath) || {
                    linesAdded: 0,
                    linesRemoved: 0,
                  };
                  fileStatuses.set(newPath, {
                    status: status,
                    oldPath: oldPath,
                    newPath: newPath,
                    linesAdded: stats.linesAdded,
                    linesRemoved: stats.linesRemoved,
                  });
                }
              }

              // Store all metadata
              this.d_patch_messages.set(patchName, messageBody);
              this.d_patch_ts.set(patchName, parseInt(timestamp));
              this.d_patch_files.set(
                patchName,
                Array.from(fileStatuses.entries())
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([_, status]) => status),
              );
            } catch (err) {
              // Skip if we can't get metadata for this patch
              console.warn(
                `Failed to get metadata for patch ${patchName}: ${err}`,
              );
            }
          }),
        );

        for (const [patchName, messageBody] of this.d_patch_messages) {
          // Extract subjects (first lines) from commit message bodies
          const firstLine = messageBody.split("\n")[0].trim();
          this.d_patch_subjects.set(patchName, firstLine);

          // Update patch stats
          this.d_patch_stats.set(patchName, {
            linesAdded: Array.from(
              this.d_patch_files.get(patchName)!.values(),
            ).reduce((acc, status) => acc + status.linesAdded, 0),
            linesRemoved: Array.from(
              this.d_patch_files.get(patchName)!.values(),
            ).reduce((acc, status) => acc + status.linesRemoved, 0),
          });
        }
      }
    } catch (e) {
      console.error(`Error refreshing STG data: ${e}`);
    }

    this.d_sig_updated.fire();
  }
}

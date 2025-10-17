import * as vscode from "vscode";
import { StackedGitExtensionStore } from "./ext_store";
import { execCLI } from "./tool_cli";

/**
 * Global extension context that stores shared state across the extension.
 */
export class GlobalContext {
  public workspaceFolder?: vscode.WorkspaceFolder;
  public out?: vscode.OutputChannel;
  public statusBarItem?: vscode.StatusBarItem;
  public store?: StackedGitExtensionStore;
  public rootPath?: string;

  public logINFO(msg: string, data?: unknown, invocation_id?: string): void {
    if (!this.out) {
      return;
    }

    const prefix = invocation_id ? `[${invocation_id}]` : "[INFO]";

    if (data !== undefined) {
      this.out.appendLine(`${prefix} ${msg}: ${JSON.stringify(data)}`);
    } else {
      this.out.appendLine(`${prefix} ${msg}`);
    }
  }

  // ============================================================================
  // Stacked Git API Methods
  // ============================================================================

  async apiStgShow(params: {
    patchName: string;
    branch?: string;
    rootPath?: string;
  }): Promise<string> {
    const argsBranch = params.branch ? ["-b", params.branch] : [];
    return await execCLI("stg", ["show", ...argsBranch, params.patchName], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiStgId(params: {
    patchName: string;
    branch?: string;
    rootPath?: string;
  }): Promise<string> {
    const argsBranch = params.branch ? ["-b", params.branch] : [];
    return await execCLI("stg", ["id", ...argsBranch, params.patchName], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiStgPush(params: {
    patchNames: string[];
    rootPath?: string;
  }): Promise<string> {
    return await execCLI("stg", ["push", ...params.patchNames], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiStgRefreshIndex(params: {
    patchName: string;
    rootPath?: string;
  }): Promise<string> {
    return await execCLI("stg", ["refresh", "--index", "-p", params.patchName], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiStgPopAll(params: { rootPath?: string }): Promise<string> {
    return await execCLI("stg", ["pop", "-a"], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiStgGoto(params: {
    patchName: string;
    rootPath?: string;
  }): Promise<string> {
    return await execCLI("stg", ["goto", params.patchName], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiStgPull(params: { rootPath?: string }): Promise<string> {
    return await execCLI("stg", ["pull", "-m"], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  // ============================================================================
  // Git API Methods
  // ============================================================================

  async apiGitCurrentBranch(params: { rootPath?: string }): Promise<string> {
    return await execCLI("git", ["rev-parse", "--abbrev-ref", "HEAD"], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiGitRevParse(params: {
    ref: string;
    rootPath?: string;
  }): Promise<string> {
    return await execCLI("git", ["rev-parse", params.ref], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiGitCatFile(params: {
    ref: string;
    rootPath?: string;
  }): Promise<string> {
    return await execCLI("git", ["cat-file", "-p", params.ref], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiGitLog(params: {
    sha: string;
    format: string;
    rootPath?: string;
  }): Promise<string> {
    return await execCLI("git", ["log", "-1", `--format=${params.format}`, params.sha], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiGitShowFile(params: {
    sha: string;
    filePath: string;
    rootPath?: string;
  }): Promise<string> {
    return await execCLI("git", ["show", `${params.sha}:${params.filePath}`], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiGitShowNameStatus(params: {
    sha: string;
    rootPath?: string;
  }): Promise<string> {
    return await execCLI("git", ["show", "--name-status", "--format=", params.sha], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiGitShowNumstat(params: {
    sha: string;
    rootPath?: string;
  }): Promise<string> {
    return await execCLI("git", ["show", "--numstat", "--format=", params.sha], {
      cwd: params.rootPath ?? this.rootPath,
    });
  }

  async apiGitShowDiff(params: {
    sha: string;
    filePath: string;
    contextLines?: number;
    rootPath?: string;
  }): Promise<string> {
    const contextArgs = params.contextLines ? [`-U${params.contextLines}`] : [];
    return await execCLI(
      "git",
      ["show", "--format=", ...contextArgs, params.sha, "--", params.filePath],
      { cwd: params.rootPath ?? this.rootPath },
    );
  }

  async apiGitRepoLastReflogSHA(params: {
    rootPath?: string;
  }): Promise<{ sha: string; date: string; message: string }> {
    const output = await execCLI(
      "git",
      ["reflog", "--all", "-n", "1", "--format=%H|%gd|%gs"],
      { cwd: params.rootPath ?? this.rootPath },
    );
    const [sha, date, message] = output.split("|");
    return { sha, date, message };
  }
}

/**
 * Global context instance used throughout the extension.
 */
export const globalContext = new GlobalContext();

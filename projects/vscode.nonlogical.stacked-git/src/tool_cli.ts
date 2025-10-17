import * as vscode from "vscode";
import * as childProcess from "child_process";
import { globalContext } from "./ext_context";

/**
 * Interface for execCLI options
 */
export interface ExecOptions {
  /** Working directory to execute in */
  cwd?: string;
  /** Environment variables to pass to the command */
  env?: Record<string, string>;
  /** Timeout in milliseconds (default: 30000) */
  timeout?: number;
  /** Whether to use a shell (default: false) */
  useShell?: boolean;
}

/**
 * Executes a shell command with the given parameters
 * @param command The command to execute
 * @param args Array of command line arguments
 * @param options Configuration options
 * @returns Promise that resolves with stdout or rejects with error
 * @throws Error if command execution fails
 *
 * @example
 *
 * // Basic usage
 * const output = await execCLI('git', ['status']);
 *
 * // With options
 * const result = await execCLI('stg', ['show', 'patch-1'], {
 *   cwd: '/path/to/repo',
 *   timeout: 5000,
 *   env: { GIT_DIR: '/custom/git/dir' }
 * });
 *
 */
export async function execCLI(
  command: string,
  args: string[] = [],
  options: ExecOptions = {},
): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    if (!command) {
      return reject(new Error("Command is required"));
    }

    const {
      cwd = vscode.workspace.rootPath || process.cwd(),
      env = {},
      timeout = 30000,
      useShell = false,
    } = options;

    // Create a process with merged environment variables
    const proc = childProcess.spawn(command, args, {
      cwd,
      env: { ...process.env, ...env },
      shell: useShell,
      windowsHide: true,
    });

    let stdout = "";
    let stderr = "";
    let timeoutId: NodeJS.Timeout | null = null;

    // Set timeout if specified
    if (timeout > 0) {
      timeoutId = setTimeout(() => {
        proc.kill();
        reject(new Error(`Command timed out after ${timeout}ms: ${command}`));
      }, timeout);
    }

    // Handle stdout data
    proc.stdout.on("data", (data: Buffer) => {
      stdout += data.toString();
    });

    // Handle stderr data
    proc.stderr.on("data", (data: Buffer) => {
      stderr += data.toString();
    });
    // Generate random ID for this invocation
    const invocationId = Math.random().toString(16).substring(2, 10);
    const startTime = Date.now();

    // Log command invocation with ID
    const logArgs = command + " " + args.map((arg) => `"${arg}"`).join(" ");
    globalContext.logINFO(`Executing: ${logArgs}`, undefined, invocationId);

    // Handle process close
    proc.on("close", (code: number) => {
      const duration = Date.now() - startTime;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }

      if (code !== 0) {
        // Log error output with ID
        globalContext.logINFO(
          `ERROR(${code}) ${duration}ms, ${logArgs}, stderr:`,
          undefined,
          invocationId,
        );
        globalContext.logINFO(
          stderr
            .split("\n")
            .map((line) => `STDERR: ${line}`)
            .join("\n"),
          undefined,
          invocationId,
        );
        reject(new Error(`Command failed with code ${code}: ${stderr}`));
      } else {
        // Log success with ID and duration
        globalContext.logINFO(
          `DONE(${code}) ${duration}ms, ${logArgs}`,
          undefined,
          invocationId,
        );
        resolve(stdout.trim());
      }
    });

    // Handle process errors
    proc.on("error", (err: Error) => {
      const duration = Date.now() - startTime;
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      // Log error with ID
      globalContext.logINFO(
        `ERROR(${err.message}) ${duration}ms, ${logArgs}`,
        undefined,
        invocationId,
      );
      reject(new Error(`Failed to execute command: ${err.message}`));
    });
  });
}

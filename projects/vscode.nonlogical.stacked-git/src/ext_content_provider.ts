import * as vscode from "vscode";
import { globalContext } from "./ext_context";
import { StackedGitPatchTreeItemType } from "./ext_model";
import { StgPatchUri } from "./ext_model";

export class StackedGitContentProvider
  implements vscode.TextDocumentContentProvider
{
  public onDidChangeEmitter = new vscode.EventEmitter<vscode.Uri>();
  onDidChange = this.onDidChangeEmitter.event;

  constructor(private readonly rootPath: string) {}

  async provideTextDocumentContent(uri: vscode.Uri): Promise<string> {
    try {
      if (uri.authority === StackedGitPatchTreeItemType.StgPatch) {
        return await this.getPatchContents(uri);
      } else if (uri.authority === StackedGitPatchTreeItemType.StgFile) {
        return await this.getFileAtPatchContents(uri);
      } else if (uri.authority === StackedGitPatchTreeItemType.StgFileDiff) {
        return await this.getFileDiffContents(uri);
      } else {
        throw new Error(`Unknown resource type: ${uri.authority}`);
      }
    } catch (err) {
      return `Error loading patch content: ${uri} ${err}`;
    }
  }

  private async getPatchContents(uri: vscode.Uri): Promise<string> {
    const ref = StgPatchUri.decodePatchRef(uri);

    if (!ref.patchName) {
      throw new Error(`Missing patch name`);
    }

    // Execute stg show command to get patch contents
    return await globalContext.apiStgShow({
      patchName: ref.patchName,
      branch: ref.branch,
      rootPath: ref.rootPath ?? this.rootPath,
    });
  }

  private async getFileAtPatchContents(uri: vscode.Uri): Promise<string> {
    const ref = StgPatchUri.decodeFileRef(uri);

    if (!ref.patchName || !ref.filePath) {
      throw new Error("Missing patch name or file path");
    }

    // Get the Git SHA for the patch
    const sha = await globalContext.apiStgId({
      patchName: ref.patchName,
      branch: ref.branch,
      rootPath: ref.rootPath ?? this.rootPath,
    });

    // Show file contents at that SHA
    return await globalContext.apiGitShowFile({
      sha,
      filePath: ref.filePath,
      rootPath: ref.rootPath ?? this.rootPath,
    });
  }

  private async getFileDiffContents(uri: vscode.Uri): Promise<string> {
    const ref = StgPatchUri.decodeFileDiffRef(uri);

    if (!ref.patchName || !ref.filePath) {
      throw new Error("Missing patch name or file path");
    }

    // Get the Git SHA for the patch
    const sha = await globalContext.apiStgId({
      patchName: ref.patchName,
      branch: ref.branch,
      rootPath: ref.rootPath ?? this.rootPath,
    });

    // Get the diff between the parent and the current SHA
    return await globalContext.apiGitShowDiff({
      sha,
      filePath: ref.filePath,
      contextLines: ref.contextLines,
      rootPath: ref.rootPath ?? this.rootPath,
    });
  }
}

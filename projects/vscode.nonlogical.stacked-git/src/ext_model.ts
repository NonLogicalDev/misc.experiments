import * as vscode from "vscode";
import * as path from "path";

//------------------------------------------------------------------------------
// Constants
//------------------------------------------------------------------------------

export const URL_DECORATION_SCHEME = "git+stg";
export const URL_DOCUMENT_SCHEME = "git+stg";

//------------------------------------------------------------------------------
// Enums
//------------------------------------------------------------------------------

export enum StackedGitPatchTreeItemType {
  StgPatch = "stg-patch",
  StgFile = "stg-file",
  StgFileDiff = "stg-file-diff",
}

//------------------------------------------------------------------------------
// Type Aliases
//------------------------------------------------------------------------------

export type StgPatchName = string;
export type GitSHA = string;

//------------------------------------------------------------------------------
// Core Interfaces
//------------------------------------------------------------------------------

export interface GitFileStatus {
  status: string;
  oldPath: string;
  newPath: string;

  linesAdded: number;
  linesRemoved: number;
}

export interface StgPatchStats {
  linesAdded: number;
  linesRemoved: number;
}

//------------------------------------------------------------------------------
// Stacked Git Metadata
//------------------------------------------------------------------------------

export interface StgStackMeta {
  version: number;

  prev: GitSHA;
  head: GitSHA;

  applied: StgPatchName[];
  unapplied: StgPatchName[];

  hidden: StgPatchName[];

  patches: {
    [key: StgPatchName]: {
      oid: GitSHA;
    };
  };
}

//------------------------------------------------------------------------------
// Patch and File Specifications
//------------------------------------------------------------------------------

export type StgPatchSpec = {
  kind: StackedGitPatchTreeItemType.StgPatch;
  spec: {
    state: string;
    name: string;
    subject: string;
    body: string;
    gitSha: string;
    gitUrl: vscode.Uri;
    branch: string;
    files?: GitFileStatus[];

    linesAdded: number;
    linesRemoved: number;
  };
};

export type StgFileSpec = {
  kind: StackedGitPatchTreeItemType.StgFile;
  spec: {
    patchName: string;
    status: string;
    path: string;

    linesAdded: number;
    linesRemoved: number;
  };
};

export type StackedGitPatchTreeItemData = StgPatchSpec | StgFileSpec;

//------------------------------------------------------------------------------
// Reference Types for URIs
//------------------------------------------------------------------------------

export interface StgPatchRef {
  patchName: string;
  branch?: string;
  rootPath?: string;
}

export interface StgPatchFileRef extends StgPatchRef {
  filePath: string;
}

export interface StgPatchFileDiffRef extends StgPatchRef {
  filePath: string;
  contextLines?: number;
}

//------------------------------------------------------------------------------
// URI Encoding/Decoding Utilities
//------------------------------------------------------------------------------

/**
 * Utility class for encoding and decoding Stacked Git URIs
 */
export class StgPatchUri {
  static encodePatchRef(ref: StgPatchRef): vscode.Uri {
    const query = new URLSearchParams();
    query.set("data", JSON.stringify(ref));

    return vscode.Uri.from({
      scheme: URL_DOCUMENT_SCHEME,
      authority: StackedGitPatchTreeItemType.StgPatch,
      path: `/${ref.patchName} (stg-patch)`,
      query: query.toString(),
    });
  }

  static decodePatchRef(uri: vscode.Uri): StgPatchRef {
    if (
      uri.scheme !== URL_DOCUMENT_SCHEME ||
      uri.authority !== StackedGitPatchTreeItemType.StgPatch
    ) {
      throw new Error(`Invalid URI: ${uri}`);
    }

    const params = new URLSearchParams(uri.query);
    return JSON.parse(params.get("data")!);
  }

  static encodeFileRef(ref: StgPatchFileRef): vscode.Uri {
    const query = new URLSearchParams();
    query.set("data", JSON.stringify(ref));

    const fileDirname = path.dirname(ref.filePath);
    const fileBasename = path.basename(ref.filePath);

    return vscode.Uri.from({
      scheme: URL_DOCUMENT_SCHEME,
      authority: StackedGitPatchTreeItemType.StgFile,
      path: `/${fileDirname}/(stg-file: ${ref.patchName}) ${fileBasename}`,
      fragment: ref.patchName,
      query: query.toString(),
    });
  }

  static decodeFileRef(uri: vscode.Uri): StgPatchFileRef {
    if (
      uri.scheme !== URL_DOCUMENT_SCHEME ||
      uri.authority !== StackedGitPatchTreeItemType.StgFile
    ) {
      throw new Error(`Invalid URI: ${uri}`);
    }

    const params = new URLSearchParams(uri.query);
    return JSON.parse(params.get("data")!);
  }

  static encodeFileDiffRef(
    ref: StgPatchFileDiffRef,
    full: boolean = false,
  ): vscode.Uri {
    const query = new URLSearchParams();
    query.set(
      "data",
      JSON.stringify({ ...ref, contextLines: full ? 100000000 : undefined }),
    );

    const fileDirname = path.dirname(ref.filePath);
    const fileBasename = path.basename(ref.filePath);
    const fullSuffix = full ? " [full]" : "";

    return vscode.Uri.from({
      scheme: URL_DOCUMENT_SCHEME,
      authority: StackedGitPatchTreeItemType.StgFileDiff,
      path: `/${fileDirname}/(stg-file-diff:${fullSuffix} ${ref.patchName}) ${fileBasename}`,
      query: query.toString(),
    });
  }

  static decodeFileDiffRef(uri: vscode.Uri): StgPatchFileDiffRef {
    if (
      uri.scheme !== URL_DOCUMENT_SCHEME ||
      uri.authority !== StackedGitPatchTreeItemType.StgFileDiff
    ) {
      throw new Error(`Invalid URI: ${uri}`);
    }

    const params = new URLSearchParams(uri.query);
    return JSON.parse(params.get("data")!);
  }
}

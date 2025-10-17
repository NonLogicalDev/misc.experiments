import * as vscode from "vscode";
import { StackedGitExtensionStore } from "./ext_store";
import { globalContext } from "./ext_context";
import {
  URL_DECORATION_SCHEME,
  StackedGitPatchTreeItemType,
  StackedGitPatchTreeItemData,
  StgPatchSpec,
  StgPatchUri,
} from "./ext_model";

export class StackedGitTreeViewDecorator
  implements vscode.FileDecorationProvider
{
  async provideFileDecoration(
    uri: vscode.Uri,
  ): Promise<vscode.FileDecoration | undefined> {
    if (uri.scheme !== URL_DECORATION_SCHEME) {
      return undefined;
    }

    if (uri.authority === StackedGitPatchTreeItemType.StgPatch) {
      const state = uri.path.substring(1); // Remove leading slash
      switch (state) {
        case "applied":
          return {
            color: new vscode.ThemeColor("testing.iconPassed"),
          };
        case "unapplied":
        case "hidden":
          return {
            color: new vscode.ThemeColor("testing.iconSkipped"),
          };
        default:
          return undefined;
      }
    }

    return undefined;
  }
}

export class StackedGitTreeViewProvider
  implements
    vscode.TreeDataProvider<
      StackedGitPatchTreeItem<StackedGitPatchTreeItemData>
    >
{
  private _onDidChangeTreeData: vscode.EventEmitter<
    | StackedGitPatchTreeItem<StackedGitPatchTreeItemData>
    | undefined
    | null
    | void
  > = new vscode.EventEmitter<
    | StackedGitPatchTreeItem<StackedGitPatchTreeItemData>
    | undefined
    | null
    | void
  >();

  readonly onDidChangeTreeData: vscode.Event<
    | StackedGitPatchTreeItem<StackedGitPatchTreeItemData>
    | undefined
    | null
    | void
  > = this._onDidChangeTreeData.event;

  private refresh_count = 0;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly store: StackedGitExtensionStore,
    private readonly rootPath: string = store.rootPath, // Get rootPath from store
  ) {
    this._onDidChangeTreeData.event((_) => {
      this.refresh_count += 1;
    });
    this.store.d_sig_updated.event((_) => {
      this.refresh();
    });
  }

  /// Methods: vscode.TreeDataProvider

  getChildren(
    element?: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Thenable<StackedGitPatchTreeItem<StackedGitPatchTreeItemData>[]> {
    // If we have an element, return its children (files)
    if (element && element.data.kind === StackedGitPatchTreeItemType.StgPatch) {
      const files = element.data.spec.files;
      const patchName = element.data.spec.name;
      if (files) {
        return Promise.resolve(
          files.map((file) => {
            return new StackedGitPatchTreeItem(`${file.newPath}`, {
              kind: StackedGitPatchTreeItemType.StgFile,
              spec: {
                patchName: patchName,
                status: file.status,
                path: file.newPath,
                linesAdded: file.linesAdded,
                linesRemoved: file.linesRemoved,
              },
            });
          }),
        );
      }
      return Promise.resolve([]);
    }

    // Root level - return patches
    return Promise.resolve([
      ...Array.from(this.store.d_patch_0_applied.values()).map((name) =>
        this.makeTreeItem(name, "applied"),
      ),
      ...Array.from(this.store.d_patch_1_unapplied.values()).map((name) =>
        this.makeTreeItem(name, "unapplied"),
      ),
      ...Array.from(this.store.d_patch_2_hidden.values()).map((name) =>
        this.makeTreeItem(name, "hidden"),
      ),
    ]);
  }

  getTreeItem(
    element: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): StackedGitPatchTreeItem<StackedGitPatchTreeItemData> {
    return element;
  }

  /// Methods: Self

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  makeTreeItem(
    name: string,
    state: string,
  ): StackedGitPatchTreeItem<StackedGitPatchTreeItemData> {
    const subject = this.store.d_patch_subjects.get(name) || "";
    const body = this.store.d_patch_messages.get(name) || "";
    const files = this.store.d_patch_files.get(name);
    const gitSha = this.store.d_patch_shas.get(name) || "";
    const branch = this.store.d_branch || "";

    const stats = this.store.d_patch_stats.get(name) || {
      linesAdded: 0,
      linesRemoved: 0,
    };

    const gitUrl = vscode.Uri.from({
      scheme: "git",
      path: `${this.rootPath}.git`,
      query: JSON.stringify({
        ref: gitSha,
      }),
    });

    return new StackedGitPatchTreeItem(name, {
      kind: StackedGitPatchTreeItemType.StgPatch,
      spec: {
        name,
        state,
        subject,
        body,
        files,
        gitSha,
        gitUrl,
        branch,

        linesAdded: stats.linesAdded,
        linesRemoved: stats.linesRemoved,
      },
    });
  }
}

export class StackedGitPatchTreeItem<
  T extends StackedGitPatchTreeItemData,
> extends vscode.TreeItem {
  constructor(
    public readonly label: string,
    public readonly data: T,
  ) {
    super(
      label,
      data.kind === StackedGitPatchTreeItemType.StgPatch && data.spec.files
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None,
    );

    // Enable filtering for different tree view items in commands / menus.
    this.contextValue = data.kind;

    const descriptionParts: string[] = [];
    switch (data.kind) {
      case StackedGitPatchTreeItemType.StgPatch: {
        descriptionParts.push(`(#${data.spec.files?.length ?? 0})`);
        descriptionParts.push(data.spec.subject);
        descriptionParts.push(
          `(+${data.spec.linesAdded}/-${data.spec.linesRemoved})`,
        );

        const tooltipFields = [`Subject: ${data.spec.subject}`];
        if (data.spec.body) {
          const justBody = data.spec.body
            .split("\n")
            .slice(1)
            .join("\n")
            .trim();
          tooltipFields.push(`\n${justBody}`);
        }

        this.resourceUri = vscode.Uri.parse(
          `${URL_DECORATION_SCHEME}://${data.kind}/${data.spec.state}`,
        );
        this.iconPath = stgStatusToIcon(data.spec.state);
        this.tooltip = tooltipFields.join("\n");
        break;
      }
      case StackedGitPatchTreeItemType.StgFile:
        descriptionParts.push(
          `(+${data.spec.linesAdded}/-${data.spec.linesRemoved})`,
        );
        this.description = descriptionParts.join(" ");

        this.iconPath = gitFileStatusIcon(data.spec.status);
        this.tooltip = `${data.spec.status} ${data.spec.path}`;
        break;
    }

    this.description = descriptionParts.join(" ");
  }
}

function stgStatusToIcon(status: string): vscode.ThemeIcon {
  switch (status) {
    case "applied":
      return new vscode.ThemeIcon(
        "pass-filled",
        new vscode.ThemeColor("testing.iconPassed"),
      );
    case "unapplied":
      return new vscode.ThemeIcon("circle-outline");
    case "hidden":
      return new vscode.ThemeIcon(
        "archive",
        new vscode.ThemeColor("testing.iconFailed"),
      );
    default:
      return new vscode.ThemeIcon("question"); // fallback icon for unknown status
  }
}

function gitFileStatusIcon(status: string): vscode.ThemeIcon {
  switch (status) {
    case "M":
      return new vscode.ThemeIcon(
        "edit",
        new vscode.ThemeColor("gitDecoration.modifiedResourceForeground"),
      );
    case "A":
      return new vscode.ThemeIcon(
        "add",
        new vscode.ThemeColor("gitDecoration.addedResourceForeground"),
      );
    case "D":
      return new vscode.ThemeIcon(
        "trash",
        new vscode.ThemeColor("gitDecoration.deletedResourceForeground"),
      );
    case "R":
      return new vscode.ThemeIcon(
        "replace",
        new vscode.ThemeColor("gitDecoration.renamedResourceForeground"),
      );
    default:
      return new vscode.ThemeIcon(
        "question",
        new vscode.ThemeColor("gitDecoration.untrackedResourceForeground"),
      );
  }
}

export class StackedGitTreeViewManager {
  constructor(
    private readonly store: StackedGitExtensionStore,
    private readonly rootPath: string,
    private readonly contentChangedNotifier: {
      onDidChangeEmitter: vscode.EventEmitter<vscode.Uri>;
    },
    private readonly stgTreeView: vscode.TreeView<
      StackedGitPatchTreeItem<StackedGitPatchTreeItemData>
    >,
  ) {}

  async copyPatchName(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgPatch) {
      return;
    }

    const stgPatchName = item.data.spec.name;
    vscode.env.clipboard.writeText(stgPatchName);
    vscode.window.showInformationMessage(`Copied patch name: ${stgPatchName}`);
  }

  async copyPatchSha(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgPatch) {
      return;
    }

    const stgPatchName = item.data.spec.name;
    const sha = this.store.d_patch_shas.get(stgPatchName);
    if (!sha) {
      vscode.window.showErrorMessage(
        `No Git SHA found for patch: ${stgPatchName}`,
      );
      return;
    }

    vscode.env.clipboard.writeText(sha);
    vscode.window.showInformationMessage(`Copied Git SHA: ${sha}`);
  }

  async copyCommitMessage(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgPatch) {
      return;
    }

    const stgPatchName = item.data.spec.name;
    const message = this.store.d_patch_messages.get(stgPatchName);
    if (!message) {
      vscode.window.showErrorMessage(
        `No commit message found for patch: ${stgPatchName}`,
      );
      return;
    }

    vscode.env.clipboard.writeText(message);
    vscode.window.showInformationMessage(
      `Copied commit message for patch: ${stgPatchName}`,
    );
  }

  async viewPatchContents(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgPatch) {
      return;
    }

    try {
      const uri = StgPatchUri.encodePatchRef({
        patchName: item.data.spec.name,
        branch: item.data.spec.branch,
        rootPath: this.rootPath,
      });

      this.contentChangedNotifier.onDidChangeEmitter.fire(uri);
      const doc = await vscode.workspace.openTextDocument(uri);
      await vscode.languages.setTextDocumentLanguage(doc, "diff");

      await vscode.window.showTextDocument(doc, {
        preview: true,
        preserveFocus: true,
        viewColumn: vscode.ViewColumn.Active,
      });
    } catch (err) {
      vscode.window.showErrorMessage(
        `Failed to show patch ${item.data.spec.name}: ${err}`,
      );
    }
  }

  async copyEditCommand(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgPatch) {
      return;
    }

    if (!item.data.spec.branch) {
      vscode.window.showErrorMessage(`No branch information available`);
      return;
    }

    const editCommand = `stg edit -b "${item.data.spec.branch}" -p "${item.data.spec.name}"`;
    vscode.env.clipboard.writeText(editCommand);
    vscode.window.showInformationMessage(`Copied edit command: ${editCommand}`);
  }

  async openSourceFile(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgFile) {
      return;
    }

    try {
      const filePath = vscode.Uri.file(
        `${this.rootPath}/${item.data.spec.path}`,
      );

      const doc = await vscode.workspace.openTextDocument(filePath);
      await vscode.window.showTextDocument(doc, {
        preview: false,
        viewColumn: vscode.ViewColumn.Active,
      });
    } catch (err) {
      vscode.window.showErrorMessage(
        `Failed to open file ${item.data.spec.path}: ${err}`,
      );
    }
  }

  async copyRefreshIndexCommand(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgPatch) {
      return;
    }

    const refreshCommand = `stg refresh --index -p "${item.data.spec.name}"`;
    vscode.env.clipboard.writeText(refreshCommand);
    vscode.window.showInformationMessage(
      `Copied refresh index command: ${refreshCommand}`,
    );
  }

  async copyGotoCommand(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgPatch) {
      return;
    }

    const gotoCommand = `stg goto "${item.data.spec.name}"`;
    vscode.env.clipboard.writeText(gotoCommand);
    vscode.window.showInformationMessage(`Copied goto command: ${gotoCommand}`);
  }

  async copySubject(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgPatch) {
      return;
    }

    const subject = item.data.spec.subject;
    if (!subject) {
      vscode.window.showErrorMessage(
        `No subject found for patch: ${item.data.spec.name}`,
      );
      return;
    }

    vscode.env.clipboard.writeText(subject);
    vscode.window.showInformationMessage(`Copied subject: ${subject}`);
  }

  async copyPushCommand(
    _item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    // Filter selections to only include StackedGitPatchTreeItemType.StgPatch-es
    const selections = this.stgTreeView.selection.filter(
      (item) => item.data.kind === StackedGitPatchTreeItemType.StgPatch,
    ) as StackedGitPatchTreeItem<StgPatchSpec>[];

    if (selections.length === 0) {
      vscode.window.showErrorMessage("No patches selected");
    }

    if (selections.length === 1) {
      const pushCommand = `stg push "${selections[0].data.spec.name}"`;
      vscode.env.clipboard.writeText(pushCommand);
      vscode.window.showInformationMessage(
        `Copied push command: ${pushCommand}`,
      );
      return;
    }

    const patchNames = selections
      .map(
        (sel) =>
          (sel as StackedGitPatchTreeItem<StackedGitPatchTreeItemData>).data,
      )
      .filter((data) => data.kind === StackedGitPatchTreeItemType.StgPatch)
      .map((data) => (data as StgPatchSpec).spec.name);

    // Ask user for command format preference
    const CHOICE_SINGLE = "Single Command";
    const CHOICE_SEPARATE = "Separate Commands";
    const choice = await vscode.window.showQuickPick(
      [CHOICE_SEPARATE, CHOICE_SINGLE],
      { placeHolder: "How would you like the push commands formatted?" },
    );

    if (choice === CHOICE_SEPARATE) {
      const pushCommands = patchNames
        .map((name) => `stg push "${name}"`)
        .join("\n");
      vscode.env.clipboard.writeText(pushCommands);
      vscode.window.showInformationMessage(
        `Copied ${selections.length} separate push commands`,
      );
    } else if (choice === CHOICE_SINGLE) {
      const pushCommand = `stg push ${patchNames.map((name) => `"${name}"`).join(" ")}`;
      vscode.env.clipboard.writeText(pushCommand);
      vscode.window.showInformationMessage(
        `Copied single push command for ${selections.length} patches`,
      );
    }
  }

  async execPushCommand(
    _item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    // Filter selections to only include StackedGitPatchTreeItemType.StgPatch-es
    const selections = this.stgTreeView.selection.filter(
      (item) => item.data.kind === StackedGitPatchTreeItemType.StgPatch,
    ) as StackedGitPatchTreeItem<StgPatchSpec>[];

    if (selections.length === 0) {
      vscode.window.showErrorMessage("No patches selected");
      return;
    }

    const patchNames = selections
      .map(
        (sel) =>
          (sel as StackedGitPatchTreeItem<StackedGitPatchTreeItemData>).data,
      )
      .filter((data) => data.kind === StackedGitPatchTreeItemType.StgPatch)
      .map((data) => (data as StgPatchSpec).spec.name);

    // Show confirmation dialog with patch list
    const patchList = patchNames.map((name) => `  • ${name}`).join("\n");
    const confirmation = await vscode.window.showInformationMessage(
      `Are you sure you want to push these patches?`,
      { modal: true, detail: `${patchList}` },
      "Yes",
      "No",
    );

    if (confirmation !== "Yes") {
      return;
    }

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Pushing patches...",
        cancellable: false,
      },
      async (_progress) => {
        try {
          // Execute the push command
          await globalContext.apiStgPush({
            patchNames,
            rootPath: this.rootPath,
          });

          vscode.window.showInformationMessage(
            `Successfully pushed ${selections.length} patch${selections.length > 1 ? "es" : ""}`,
          );

          // Refresh the view
          this.store.reload();
        } catch (err) {
          vscode.window.showErrorMessage(`Failed to push patches: ${err}`);
        }
      },
    );
  }

  async refreshFromIndex(): Promise<void> {
    const patchNames = Array.from(this.store.d_patch_0_applied.values()).map(
      (name) => ({
        label: name,
        description: this.store.d_patch_subjects.get(name) || "",
      }),
    );

    const selectedPatch = await vscode.window.showQuickPick(patchNames, {
      placeHolder: "Select patch to refresh from index",
    });

    if (!selectedPatch) {
      vscode.window.showErrorMessage("No patch selected");
      return;
    }

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.SourceControl,
        title: `Refreshing patch "${selectedPatch.label}"...`,
        cancellable: false,
      },
      async (_progress) => {
        await globalContext.apiStgRefreshIndex({
          patchName: selectedPatch.label,
          rootPath: this.rootPath,
        });

        vscode.window.showInformationMessage(
          `Refreshed patch: ${selectedPatch.label}`,
        );
        this.store.reload();
      },
    );
  }

  async popAll(): Promise<void> {
    try {
      const patchNames = Array.from(this.store.d_patch_0_applied.values()).map(
        (name) => ({
          label: name,
          description: this.store.d_patch_subjects.get(name) || "",
        }),
      );

      // Show confirmation dialog
      const patchList = patchNames.map((p) => `  • ${p.label}`).join("\n");
      const choice = await vscode.window.showWarningMessage(
        `Are you sure you want to pop all ${patchNames.length} patches?`,
        { modal: true, detail: `${patchList}` },
        "Yes",
        "No",
      );

      if (choice !== "Yes") {
        return;
      }

      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: "Popping all patches...",
          cancellable: false,
        },
        async (_progress) => {
          // Execute stg pop -a command
          await globalContext.apiStgPopAll({ rootPath: this.rootPath });

          // Refresh the view
          this.store.reload();

          vscode.window.showInformationMessage(
            "Successfully popped all patches",
          );
        },
      );
    } catch (err) {
      vscode.window.showErrorMessage(`Failed to pop all patches: ${err}`);
    }
  }

  async viewSourceAtPatch(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgFile) {
      return;
    }

    try {
      const uri = StgPatchUri.encodeFileRef({
        patchName: item.data.spec.patchName,
        filePath: item.data.spec.path,
        branch: this.store.d_branch,
        rootPath: this.rootPath,
      });

      this.contentChangedNotifier.onDidChangeEmitter.fire(uri);
      const doc = await vscode.workspace.openTextDocument(uri);
      await vscode.window.showTextDocument(doc, {
        preview: true,
        preserveFocus: true,
        viewColumn: vscode.ViewColumn.Active,
      });
    } catch (err) {
      vscode.window.showErrorMessage(
        `Failed to show file ${item.data.spec.path} at patch ${item.data.spec.patchName}: ${err}`,
      );
    }
  }

  async copyFilePath(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgFile) {
      return;
    }

    vscode.env.clipboard.writeText(item.data.spec.path);
    vscode.window.showInformationMessage(
      `Copied file path: ${item.data.spec.path}`,
    );
  }

  async gotoPatch(
    item?: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    let patchName = undefined;
    if (item?.data?.kind === StackedGitPatchTreeItemType.StgPatch) {
      patchName = item.data.spec.name;
    } else {
      // Ask which patch we want to go to (applied/unapplied)
      const patchNames = [
        ...this.store.d_patch_0_applied,
        undefined,
        ...this.store.d_patch_1_unapplied,
      ].map((name) => {
        if (name === undefined) {
          return {
            label: "",
            kind: vscode.QuickPickItemKind.Separator,
          };
        }
        return {
          label: name,
          description: this.store.d_patch_subjects.get(name) || "",
        };
      });

      const selectedPatch = await vscode.window.showQuickPick(patchNames, {
        placeHolder: "Select patch to goto",
      });

      if (selectedPatch) {
        patchName = selectedPatch.label;
      }
    }

    if (!patchName) {
      vscode.window.showErrorMessage("No patch selected");
      return;
    }

    // Show confirmation dialog
    const choice = await vscode.window.showWarningMessage(
      `Are you sure you want to goto patch: ${patchName}?`,
      { modal: true },
      "Yes",
      "No",
    );

    if (choice !== "Yes") {
      return;
    }

    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Goto patch...",
        cancellable: false,
      },
      async (_progress) => {
        await globalContext.apiStgGoto({
          patchName: patchName!,
          rootPath: this.rootPath,
        });

        vscode.window.showInformationMessage(
          `Successfully goto patch: ${patchName}`,
        );
        this.store.reload();
      },
    );
  }

  async pullRemote(): Promise<void> {
    try {
      // Show confirmation dialog
      const choice = await vscode.window.showWarningMessage(
        "Pull and merge remote changes?",
        { modal: true, detail: "This will execute 'stg pull -m'" },
        "Yes",
        "No",
      );

      if (choice !== "Yes") {
        return;
      }

      await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Notification,
          title: "Pulling remote changes...",
          cancellable: false,
        },
        async (_progress) => {
          // Execute stg pull -m command
          await globalContext.apiStgPull({ rootPath: this.rootPath });

          // Refresh the view
          this.store.reload();

          vscode.window.showInformationMessage(
            "Successfully pulled remote changes",
          );
        },
      );
    } catch (err) {
      vscode.window.showErrorMessage(`Failed to pull remote changes: ${err}`);
    }
  }

  async viewFileChanges(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgFile) {
      return;
    }

    try {
      const patchName = item.data.spec.patchName;
      const filePath = item.data.spec.path;

      const uri = StgPatchUri.encodeFileDiffRef({
        patchName,
        filePath,
        branch: this.store.d_branch,
        rootPath: this.rootPath,
      });

      this.contentChangedNotifier.onDidChangeEmitter.fire(uri);
      const doc = await vscode.workspace.openTextDocument(uri);
      await vscode.languages.setTextDocumentLanguage(doc, "diff");

      await vscode.window.showTextDocument(doc, {
        preview: true,
        viewColumn: vscode.ViewColumn.Active,
        preserveFocus: true,
      });
    } catch (err) {
      vscode.window.showErrorMessage(`Failed to view file changes: ${err}`);
    }
  }

  async viewFileChangesFull(
    item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>,
  ): Promise<void> {
    if (item.data.kind !== StackedGitPatchTreeItemType.StgFile) {
      return;
    }

    try {
      const patchName = item.data.spec.patchName;
      const filePath = item.data.spec.path;

      const uri = StgPatchUri.encodeFileDiffRef(
        {
          patchName,
          filePath,
          branch: this.store.d_branch,
          rootPath: this.rootPath,
        },
        true,
      );

      this.contentChangedNotifier.onDidChangeEmitter.fire(uri);
      const doc = await vscode.workspace.openTextDocument(uri);
      await vscode.languages.setTextDocumentLanguage(doc, "diff");

      await vscode.window.showTextDocument(doc, {
        preview: true,
        viewColumn: vscode.ViewColumn.Active,
        preserveFocus: true,
      });
    } catch (err) {
      vscode.window.showErrorMessage(`Failed to view file changes: ${err}`);
    }
  }
}

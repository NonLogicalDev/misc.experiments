import * as vscode from "vscode";
import { globalContext } from "./ext_context";
import {
  URL_DOCUMENT_SCHEME,
  StackedGitPatchTreeItemType,
  StackedGitPatchTreeItemData,
} from "./ext_model";
import { StackedGitExtensionStore } from "./ext_store";
import {
  StackedGitTreeViewProvider,
  StackedGitPatchTreeItem,
  StackedGitTreeViewManager,
  StackedGitTreeViewDecorator,
} from "./ext_view_tree";
import { StackedGitContentProvider } from "./ext_content_provider";

//------------------------------------------------------------------------------
// References:
//------------------------------------------------------------------------------
// * https://stackoverflow.com/questions/74449432/how-to-add-and-select-color-for-nodes-tree-view-items-in-explorer-view-in-my-vsc
// * https://code.visualstudio.com/api/extension-guides/tree-view#registering-the-treedataprovider
// * https://github.com/holazz/vscode-reveal/blob/main/package.json
// * https://github.com/tianjianchn/code-explorer-vscode/blob/main/package.json

//------------------------------------------------------------------------------
// Registration:
//------------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext) {
  // Helper function to subscribe to a disposable item
  const _subscribed = <T extends vscode.Disposable>(item: T): T => {
    context.subscriptions.push(item);
    return item;
  };

  const rootPath =
    vscode.workspace.workspaceFolders &&
    vscode.workspace.workspaceFolders.length > 0
      ? vscode.workspace.workspaceFolders[0].uri.fsPath
      : undefined;

  // Create the output channel.
  globalContext.out = _subscribed(
    vscode.window.createOutputChannel("Stacked Git"),
  );
  globalContext.rootPath = rootPath ?? "";
  globalContext.logINFO("STARTED");

  // Create and register the store
  globalContext.store = new StackedGitExtensionStore(rootPath ?? "");
  const store = globalContext.store;

  // Create and register the status bar
  const statusBar = _subscribed(new StackedGitStatusBar(store));

  // Register the patch content provider
  const stgContentProvider = new StackedGitContentProvider(rootPath ?? "");
  _subscribed(
    vscode.workspace.registerTextDocumentContentProvider(
      URL_DOCUMENT_SCHEME,
      stgContentProvider,
    ),
  );

  // Register the decoration provider
  _subscribed(
    vscode.window.registerFileDecorationProvider(
      new StackedGitTreeViewDecorator(),
    ),
  );

  // Create and register a new webview
  const stgTreeViewDataProvider = new StackedGitTreeViewProvider(
    context.extension.extensionUri,
    store,
    rootPath ?? "",
  );

  // const gitExt = vscode.extensions.getExtension("vscode.git")?.activate();
  // globalContext.gitExt = gitExt;

  // Register the tree view to add title actions
  const stgTreeView = _subscribed(
    vscode.window.createTreeView("stackedGit", {
      treeDataProvider: stgTreeViewDataProvider,
      showCollapseAll: true,
      canSelectMany: true,
    }),
  );

  // Create the tree view manager
  const treeViewManager = new StackedGitTreeViewManager(
    store,
    rootPath ?? "",
    stgContentProvider,
    stgTreeView,
  );

  // Refresh when view becomes visible
  stgTreeView.onDidChangeVisibility((e) => {
    if (e.visible) {
      store.reload();
    }
  });

  // Register the refresh command
  _subscribed(
    vscode.commands.registerCommand("stackedGit.reload", () => store.reload()),
  );

  // Register commands for copying patch info
  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.copyPatchName",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.copyPatchName(item),
    ),
  );

  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.copyPatchSha",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.copyPatchSha(item),
    ),
  );

  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.copyCommitMessage",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.copyCommitMessage(item),
    ),
  );

  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.viewPatchContents",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.viewPatchContents(item),
    ),
  );

  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.copyEditCommand",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.copyEditCommand(item),
    ),
  );

  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.openSourceFile",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.openSourceFile(item),
    ),
  );

  // Add new command registration for refresh index
  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.copyRefreshIndexCommand",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.copyRefreshIndexCommand(item),
    ),
  );

  // Add new command registration for goto command
  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.copyGotoCommand",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.copyGotoCommand(item),
    ),
  );

  // Add new command registration for copying subject
  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.copySubject",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.copySubject(item),
    ),
  );

  // Add new command registration for push command
  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.copyPushCommand",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.copyPushCommand(item),
    ),
  );

  // Add new command registration for executing push command
  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.execPushCommand",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.execPushCommand(item),
    ),
  );

  _subscribed(
    vscode.commands.registerCommand("stackedGit.refreshFromIndex", () =>
      treeViewManager.refreshFromIndex(),
    ),
  );

  _subscribed(
    vscode.commands.registerCommand("stackedGit.popAll", () =>
      treeViewManager.popAll(),
    ),
  );

  // Add new command registration for viewing source at patch
  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.viewSourceAtPatch",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.viewSourceAtPatch(item),
    ),
  );

  // Add new command for copying file paths
  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.copyFilePath",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.copyFilePath(item),
    ),
  );

  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.gotoPatch",
      (item?: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.gotoPatch(item),
    ),
  );

  // Add new command registration for pull remote
  _subscribed(
    vscode.commands.registerCommand("stackedGit.pullRemote", () =>
      treeViewManager.pullRemote(),
    ),
  );

  // Add new command registration for viewing file changes
  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.viewFileChanges",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.viewFileChanges(item),
    ),
  );

  _subscribed(
    vscode.commands.registerCommand(
      "stackedGit.viewFileChangesFull",
      (item: StackedGitPatchTreeItem<StackedGitPatchTreeItemData>) =>
        treeViewManager.viewFileChangesFull(item),
    ),
  );

  // Register the status bar click command
  _subscribed(
    vscode.commands.registerCommand("stackedGit.statusBarClick", () =>
      statusBar.handleClick(),
    ),
  );

  // Set up periodic refresh of store
  const refreshInterval = vscode.workspace
    .getConfiguration("stackedGit")
    .get("refreshInterval", 60); // default 60 seconds

  const timer = setInterval(() => {
    store.reload();
  }, refreshInterval * 1000);

  // Make sure to clear the interval when deactivating
  _subscribed({
    dispose: () => clearInterval(timer),
  });
}

export function deactivate() {}

//------------------------------------------------------------------------------
// Views / Providers / Decorators:
//------------------------------------------------------------------------------

class StackedGitStatusBar implements vscode.Disposable {
  private statusBarItem: vscode.StatusBarItem;
  private readonly store: StackedGitExtensionStore;

  constructor(store: StackedGitExtensionStore) {
    this.store = store;

    // Create status bar item in the left section with appropriate priority
    this.statusBarItem = vscode.window.createStatusBarItem(
      vscode.StatusBarAlignment.Left,
      100,
    );

    this.statusBarItem.command = "stackedGit.statusBarClick";
    this.statusBarItem.tooltip = "Click to access Stacked Git operations";

    // Listen to store updates
    this.store.d_sig_updated.event(() => {
      this.updateStatus();
    });

    // Listen to configuration changes
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("stackedGit.statusBar.enabled")) {
        this.updateVisibility();
      }
    });

    // Initial setup
    this.updateVisibility();
    this.updateStatus();
  }

  private updateVisibility(): void {
    const isEnabled = vscode.workspace
      .getConfiguration("stackedGit")
      .get("statusBar.enabled", true);
    if (isEnabled) {
      this.statusBarItem.show();
    } else {
      this.statusBarItem.hide();
    }
  }

  private updateStatus(): void {
    const appliedPatches = this.store.d_patch_0_applied;
    const unappliedPatches = this.store.d_patch_1_unapplied;
    const hiddenPatches = this.store.d_patch_2_hidden;

    const currentPatch =
      appliedPatches.length > 0
        ? appliedPatches[appliedPatches.length - 1]
        : null;
    const position = appliedPatches.length;
    const stackLength = appliedPatches.length + unappliedPatches.length;
    const archivedCount = hiddenPatches.length;

    if (currentPatch) {
      this.statusBarItem.text = `stg: ${currentPatch} [${position}/${stackLength}/${archivedCount}]`;
    } else if (stackLength > 0) {
      this.statusBarItem.text = `stg: (no patch) [0/${stackLength}/${archivedCount}]`;
    } else {
      this.statusBarItem.text = `stg: (no patches) [0/0/${archivedCount}]`;
    }

    // Update tooltip with more detailed information
    let tooltip = "Stacked Git Status\n";
    tooltip += `Current patch: ${currentPatch || "(none)"}\n`;
    tooltip += `Position in stack: ${position}/${stackLength}\n`;
    tooltip += `Archived patches: ${archivedCount}\n`;
    tooltip += "\nClick for operations menu";

    this.statusBarItem.tooltip = tooltip;
  }

  async handleClick(): Promise<void> {
    const items: vscode.QuickPickItem[] = [
      {
        label: "$(git-branch) Goto Patch",
        description: "Switch to a specific patch",
      },
      {
        label: "$(arrow-up) Push Patch",
        description: "Push selected patches",
      },
      {
        label: "$(arrow-down) Pop All Patches",
        description: "Pop all applied patches",
      },
      {
        label: "$(refresh) Refresh From Index",
        description: "Refresh a patch from the index",
      },
      {
        label: "$(list-tree) Open Stacked Git View",
        description: "Open the main Stacked Git tree view",
      },
    ];

    const selection = await vscode.window.showQuickPick(items, {
      placeHolder: "Select a Stacked Git operation",
    });

    if (!selection) {
      return;
    }

    switch (selection.label) {
      case "$(git-branch) Goto Patch":
        await vscode.commands.executeCommand("stackedGit.gotoPatch");
        break;
      case "$(arrow-up) Push Patch": {
        // Show quick pick for applied patches to push
        const patchesToPush = this.store.d_patch_1_unapplied.map((name) => ({
          label: name,
          description: this.store.d_patch_subjects.get(name) || "",
        }));

        if (patchesToPush.length === 0) {
          vscode.window.showInformationMessage("No unapplied patches to push");
          return;
        }

        const selectedPatch = await vscode.window.showQuickPick(patchesToPush, {
          placeHolder: "Select patch to push",
        });

        if (selectedPatch) {
          await vscode.commands.executeCommand("stackedGit.execPushCommand", {
            data: {
              kind: StackedGitPatchTreeItemType.StgPatch,
              spec: { name: selectedPatch.label },
            },
          });
        }
        break;
      }
      case "$(arrow-down) Pop All Patches":
        await vscode.commands.executeCommand("stackedGit.popAll");
        break;
      case "$(refresh) Refresh From Index":
        await vscode.commands.executeCommand("stackedGit.refreshFromIndex");
        break;
      case "$(list-tree) Open Stacked Git View":
        await vscode.commands.executeCommand("stackedGit.focus");
        break;
    }
  }

  dispose(): void {
    this.statusBarItem.dispose();
  }
}

//------------------------------------------------------------------------------
// Helpers
//------------------------------------------------------------------------------

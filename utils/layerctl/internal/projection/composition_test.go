package projection_test

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
)

func compositionFixture(t *testing.T) (string, *projection.CompositionService) {
	t.Helper()
	for k, v := range map[string]string{"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"} {
		t.Setenv(k, v)
	}
	root := filepath.Join(t.TempDir(), "definitions")
	if err := os.Mkdir(root, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, root, "init", "-q")
	git := &gitrepo.Repository{Root: root}
	return root, &projection.CompositionService{Definition: &definition.Repository{Root: root}, Git: git, Log: log.New(io.Discard, "", 0)}
}
func sourceFixture(t *testing.T, filename, text string) (string, string) {
	t.Helper()
	root := filepath.Join(t.TempDir(), "source")
	if err := os.Mkdir(root, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, root, "init", "-q")
	writeFile(t, filepath.Join(root, filename), text)
	gitRun(t, root, "add", ".")
	gitRun(t, root, "commit", "-qm", "source")
	return root, gitOutput(t, root, "rev-parse", "HEAD")
}

func TestCompositionCreatesOneCommitWithMultipleSourceParents(t *testing.T) {
	ctx := context.Background()
	definitionRoot, s := compositionFixture(t)
	sourceA, commitA := sourceFixture(t, "root.txt", "root\n")
	// Even files matched by the source's ignore rules belong in its tree when
	// the source explicitly tracks them.
	writeFile(t, filepath.Join(sourceA, ".gitignore"), "ignored.bin\n")
	writeFile(t, filepath.Join(sourceA, "ignored.bin"), "tracked despite ignore\n")
	gitRun(t, sourceA, "add", ".gitignore")
	gitRun(t, sourceA, "add", "-f", "ignored.bin")
	gitRun(t, sourceA, "commit", "-qm", "Track ignored file")
	commitA = gitOutput(t, sourceA, "rev-parse", "HEAD")
	sourceB, commitB := sourceFixture(t, "child.txt", "child\n")
	s.Definition.Layers = []definition.Unit{{ID: "0001-sources", Message: []byte("Import sources\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: sourceA, Dir: ""}, {Kind: "git-clone", URL: sourceB, Dir: "vendor/child"}}}, {ID: "0002-overlay", Message: []byte("Add local file\n"), Operations: []definition.Operation{{Kind: "overlay", Overlay: []definition.OverlayEntry{{Path: "local.txt", Mode: "100644", Data: []byte("local\n")}}}}}}
	workspace := filepath.Join(t.TempDir(), "workspace")
	result, err := s.Create(ctx, projection.CreateRequest{Name: "combined", WorktreePath: workspace})
	if err != nil {
		t.Fatal(err)
	}
	assertFile(t, filepath.Join(workspace, "root.txt"), "root\n")
	assertFile(t, filepath.Join(workspace, "vendor/child/child.txt"), "child\n")
	assertFile(t, filepath.Join(workspace, "local.txt"), "local\n")
	if got := gitOutput(t, workspace, "show", "HEAD:ignored.bin"); got != "tracked despite ignore" {
		t.Fatalf("tracked ignored source file omitted: %q", got)
	}
	if got := gitOutput(t, workspace, "show", "HEAD:root.txt"); got != "root" {
		t.Fatalf("root file not committed: %q", got)
	}
	if got := gitOutput(t, workspace, "show", "HEAD:vendor/child/child.txt"); got != "child" {
		t.Fatalf("child file not committed: %q", got)
	}
	if got, err := s.Through(ctx, "combined"); err != nil || got != "0002-overlay" {
		t.Fatalf("Through=%q err=%v", got, err)
	}

	parents := strings.Fields(gitOutput(t, workspace, "show", "-s", "--format=%P", "HEAD^"))
	if len(parents) != 2 || parents[0] != commitA || parents[1] != commitB {
		t.Fatalf("source parents: %v", parents)
	}
	if got := gitOutput(t, workspace, "rev-list", "--count", "--first-parent", "HEAD"); got == "" {
		t.Fatal("missing workspace history")
	}
	if _, err := os.Stat(filepath.Join(workspace, "vendor/child/.git")); !os.IsNotExist(err) {
		t.Fatalf("nested Git metadata: %v", err)
	}
	if cmd := exec.Command("git", "-C", definitionRoot, "cat-file", "-e", commitA+"^{commit}"); cmd.Run() == nil {
		t.Fatal("source commit leaked into definition repository")
	}
	if result.Head != gitOutput(t, workspace, "rev-parse", "HEAD") {
		t.Fatal("returned head does not match workspace")
	}
	listed, err := s.List(ctx)
	if err != nil || len(listed) != 1 || listed[0].Name != "combined" {
		t.Fatalf("List=%v error=%v", listed, err)
	}
	if err := s.Delete(ctx, "combined"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(workspace); !os.IsNotExist(err) {
		t.Fatalf("workspace not removed: %v", err)
	}
}

func TestCompositionRejectsExistingDestinationAndPreservesIt(t *testing.T) {
	ctx := context.Background()
	_, s := compositionFixture(t)
	source, _ := sourceFixture(t, "a.txt", "a\n")
	s.Definition.Layers = []definition.Unit{{ID: "0001-source", Message: []byte("Source\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: source, Dir: ""}}}}
	workspace := filepath.Join(t.TempDir(), "existing")
	if err := os.Mkdir(workspace, 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(workspace, "keep"), "keep")
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "existing", WorktreePath: workspace}); err == nil {
		t.Fatal("accepted existing workspace")
	}
	assertFile(t, filepath.Join(workspace, "keep"), "keep")
	if _, err := s.Get(ctx, "existing"); err == nil {
		t.Fatal("failed create left registered composition")
	}
}

func TestCompositionDeleteRefusesMismatchedOwnership(t *testing.T) {
	ctx := context.Background()
	_, s := compositionFixture(t)
	source, _ := sourceFixture(t, "a.txt", "a\n")
	s.Definition.Layers = []definition.Unit{{ID: "0001-source", Message: []byte("Source\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: source, Dir: ""}}}}
	workspace := filepath.Join(t.TempDir(), "workspace")
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "protected", WorktreePath: workspace}); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(workspace, ".git/layerctl-owner"), "different")
	if err := s.Delete(ctx, "protected"); err == nil {
		t.Fatal("deleted unowned workspace")
	}
	assertFile(t, filepath.Join(workspace, "a.txt"), "a\n")
}

func TestCompositionThroughAndDefaultWorkspace(t *testing.T) {
	ctx := context.Background()
	_, s := compositionFixture(t)
	source, _ := sourceFixture(t, "first.txt", "one\n")
	s.Definition.Layers = []definition.Unit{{ID: "0001-first", Message: []byte("First\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: source, Dir: ""}}}, {ID: "0002-second", Message: []byte("Second\n"), Operations: []definition.Operation{{Kind: "overlay", Overlay: []definition.OverlayEntry{{Path: "later.txt", Mode: "100644", Data: []byte("later\n")}}}}}}
	result, err := s.Create(ctx, projection.CreateRequest{Name: "partial", Through: "0001-first"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(result.WorktreePath, "later.txt")); !os.IsNotExist(err) {
		t.Fatalf("unexpected later layer: %v", err)
	}
	if id, err := s.Through(ctx, "partial"); err != nil || id != "0001-first" {
		t.Fatalf("through = %q, %v", id, err)
	}
	if err := s.Delete(ctx, "partial"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(result.WorktreePath); !os.IsNotExist(err) {
		t.Fatalf("default workspace remains: %v", err)
	}
}

func TestLaterCloneMakesPriorWorkspaceFirstParent(t *testing.T) {
	ctx := context.Background()
	_, s := compositionFixture(t)
	sourceA, commitA := sourceFixture(t, "a.txt", "a\n")
	sourceB, commitB := sourceFixture(t, "b.txt", "b\n")
	s.Definition.Layers = []definition.Unit{{ID: "0001-first", Message: []byte("First\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: sourceA, Dir: ""}}}, {ID: "0002-second", Message: []byte("Second\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: sourceB, Dir: "vendor"}}}}
	p, err := s.Create(ctx, projection.CreateRequest{Name: "parents"})
	if err != nil {
		t.Fatal(err)
	}
	parents := strings.Fields(gitOutput(t, p.WorktreePath, "show", "-s", "--format=%P", "HEAD"))
	if len(parents) != 2 || parents[1] != commitB {
		t.Fatalf("second layer parents = %v", parents)
	}
	if got := gitOutput(t, p.WorktreePath, "show", "-s", "--format=%P", parents[0]); got != commitA {
		t.Fatalf("first layer parent = %q, want %q", got, commitA)
	}
	if got := gitOutput(t, p.WorktreePath, "show", "HEAD:vendor/b.txt"); got != "b" {
		t.Fatalf("missing later import: %q", got)
	}
}

func TestCompositionKeepsShallowHistoryInWorkspaceOnly(t *testing.T) {
	ctx := context.Background()
	definitions, s := compositionFixture(t)
	source, _ := sourceFixture(t, "history.txt", "one\n")
	writeFile(t, filepath.Join(source, "history.txt"), "two\n")
	gitRun(t, source, "add", ".")
	gitRun(t, source, "commit", "-qm", "second")
	s.Definition.Layers = []definition.Unit{{ID: "0001-source", Message: []byte("Import\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: "file://" + source, Dir: "", Depth: 1}}}}
	p, err := s.Create(ctx, projection.CreateRequest{Name: "shallow"})
	if err != nil {
		t.Fatal(err)
	}
	parent := gitOutput(t, p.WorktreePath, "rev-parse", "HEAD^")
	if got := gitOutput(t, p.WorktreePath, "rev-list", "--count", parent); got != "1" {
		t.Fatalf("source history depth = %s", got)
	}
	if got := gitOutput(t, p.WorktreePath, "rev-parse", "--is-shallow-repository"); got != "true" {
		t.Fatalf("workspace shallow status = %s", got)
	}
	if _, err := os.Stat(filepath.Join(definitions, ".git/shallow")); !os.IsNotExist(err) {
		t.Fatalf("definition repo shallow state changed: %v", err)
	}
}

func conflictCompositionFixture(t *testing.T) (*projection.CompositionService, string, string, string, string) {
	t.Helper()
	definitions, s := compositionFixture(t)
	sourceA, base := sourceFixture(t, "file.txt", "base\n")
	writeFile(t, filepath.Join(sourceA, "file.txt"), "feature\n")
	gitRun(t, sourceA, "add", "file.txt")
	gitRun(t, sourceA, "commit", "-qm", "feature")
	feature := gitOutput(t, sourceA, "rev-parse", "HEAD")
	patch := filepath.Join(t.TempDir(), "feature.patch")
	cmd := exec.Command("git", "-C", sourceA, "diff", "--binary", "--full-index", base, feature, "--", "file.txt")
	data, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(patch, data, 0644); err != nil {
		t.Fatal(err)
	}
	gitRun(t, sourceA, "reset", "--hard", base)
	writeFile(t, filepath.Join(sourceA, "file.txt"), "upstream\n")
	gitRun(t, sourceA, "add", "file.txt")
	gitRun(t, sourceA, "commit", "-qm", "upstream")
	sourceHead := gitOutput(t, sourceA, "rev-parse", "HEAD")
	sourceB, secondHead := sourceFixture(t, "after.txt", "later\n")
	s.Definition.Layers = []definition.Unit{{ID: "0001-compose", Message: []byte("Composed\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: sourceA, Dir: ""}, {Kind: "patch", Path: patch}, {Kind: "git-clone", URL: sourceB, Dir: "vendor"}}}}
	return s, definitions, patch, sourceHead, secondHead
}
func TestCompositionContinueRunsRemainingOperationsAfterConflict(t *testing.T) {
	ctx := context.Background()
	s, _, _, first, second := conflictCompositionFixture(t)
	workspace := filepath.Join(t.TempDir(), "conflict")
	result, err := s.Create(ctx, projection.CreateRequest{Name: "conflicted", WorktreePath: workspace})
	var conflict *projection.CompositionConflictError
	if !errors.As(err, &conflict) || result.WorktreePath != workspace {
		t.Fatalf("Create = %+v, %v", result, err)
	}
	if _, err := os.Stat(filepath.Join(workspace, "vendor/after.txt")); !os.IsNotExist(err) {
		t.Fatalf("later clone ran before resolution: %v", err)
	}
	writeFile(t, filepath.Join(workspace, "file.txt"), "resolved\n")
	fresh := &projection.CompositionService{Definition: s.Definition, Git: s.Git, Log: s.Log}
	result, err = fresh.Continue(ctx, "conflicted")
	if err != nil {
		t.Fatal(err)
	}
	if got := gitOutput(t, workspace, "show", "HEAD:file.txt"); got != "resolved" {
		t.Fatalf("resolved content = %q", got)
	}
	if got := gitOutput(t, workspace, "show", "HEAD:vendor/after.txt"); got != "later" {
		t.Fatalf("later operation content = %q", got)
	}
	if got := strings.Fields(gitOutput(t, workspace, "show", "-s", "--format=%P", "HEAD")); len(got) != 2 || got[0] != first || got[1] != second {
		t.Fatalf("parents=%v", got)
	}
	if result.Base != result.Head {
		t.Fatalf("finished base/head = %+v", result)
	}
}
func TestCompositionContinueRejectsChangedDefinition(t *testing.T) {
	ctx := context.Background()
	s, _, patch, _, _ := conflictCompositionFixture(t)
	workspace := filepath.Join(t.TempDir(), "conflict")
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "changed", WorktreePath: workspace}); err == nil {
		t.Fatal("expected conflict")
	}
	writeFile(t, patch, "changed patch\n")
	writeFile(t, filepath.Join(workspace, "file.txt"), "resolved\n")
	if _, err := s.Continue(ctx, "changed"); err == nil || !strings.Contains(err.Error(), "definitions changed") {
		t.Fatalf("continue changed definitions = %v", err)
	}
	if _, err := os.Stat(filepath.Join(workspace, "vendor/after.txt")); !os.IsNotExist(err) {
		t.Fatalf("later clone unexpectedly ran: %v", err)
	}
}
func TestCompositionContinueRefusesUncertainOperationAndWrongOwner(t *testing.T) {
	ctx := context.Background()
	s, definitions, _, _, _ := conflictCompositionFixture(t)
	workspace := filepath.Join(t.TempDir(), "conflict")
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "uncertain", WorktreePath: workspace}); err == nil {
		t.Fatal("expected conflict")
	}
	recordPath := filepath.Join(definitions, ".git/layerctl/compositions/uncertain/record.json")
	data, err := os.ReadFile(recordPath)
	if err != nil {
		t.Fatal(err)
	}
	var state map[string]any
	if err := json.Unmarshal(data, &state); err != nil {
		t.Fatal(err)
	}
	state["stepInProgress"] = true
	state["resolving"] = false
	data, err = json.Marshal(state)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(recordPath, data, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Continue(ctx, "uncertain"); err == nil || !strings.Contains(err.Error(), "uncertain") {
		t.Fatalf("continue uncertain = %v", err)
	}
	writeFile(t, filepath.Join(workspace, ".git/layerctl-owner"), "wrong")
	if _, err := s.Continue(ctx, "uncertain"); err == nil || !strings.Contains(err.Error(), "ownership") {
		t.Fatalf("continue wrong owner = %v", err)
	}
	if err := s.Delete(ctx, "uncertain"); err == nil {
		t.Fatal("deleted wrong owner")
	}
}

func TestCompositionSkipsDisabledLayersAndValidatesDependencies(t *testing.T) {
	ctx := context.Background()
	_, s := compositionFixture(t)
	source, _ := sourceFixture(t, "first.txt", "one\n")
	s.Definition.Layers = []definition.Unit{
		{ID: "0001-first", Message: []byte("First\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: source, Dir: ""}}},
		{ID: "0002-disabled", Disabled: true, Message: []byte("Skip\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: "/missing/should-not-fetch", Dir: "skip"}}},
		{ID: "0003-last", DependsOn: []string{"0001-first"}, Message: []byte("Last\n"), Operations: []definition.Operation{{Kind: "overlay", Overlay: []definition.OverlayEntry{{Path: "last.txt", Mode: "100644", Data: []byte("last\n")}}}}},
	}
	p, err := s.Create(ctx, projection.CreateRequest{Name: "enabled"})
	if err != nil {
		t.Fatal(err)
	}
	if got := gitOutput(t, p.WorktreePath, "show", "HEAD:last.txt"); got != "last" {
		t.Fatalf("missing enabled layer: %q", got)
	}
	if got := gitOutput(t, p.WorktreePath, "show", "-s", "--format=%s", "HEAD^"); got != "First" {
		t.Fatalf("disabled layer was not skipped: %q", got)
	}
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "disabled", Through: "0002-disabled"}); err == nil || !strings.Contains(err.Error(), "disabled") {
		t.Fatalf("through disabled = %v", err)
	}
	s.Definition.Layers[2].DependsOn = []string{"0002-disabled"}
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "missing-dep"}); err == nil || !strings.Contains(err.Error(), "requires unavailable") {
		t.Fatalf("missing dependency = %v", err)
	}
}

func TestCompositionContinueFinalizesAfterLastLayerCheckpoint(t *testing.T) {
	ctx := context.Background()
	definitions, s := compositionFixture(t)
	source, _ := sourceFixture(t, "a.txt", "a\n")
	s.Definition.Layers = []definition.Unit{{ID: "0001-source", Message: []byte("Source\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: source, Dir: ""}}}}
	p, err := s.Create(ctx, projection.CreateRequest{Name: "finish"})
	if err != nil {
		t.Fatal(err)
	}
	recordPath := filepath.Join(definitions, ".git/layerctl/compositions/finish/record.json")
	data, err := os.ReadFile(recordPath)
	if err != nil {
		t.Fatal(err)
	}
	var state map[string]any
	if err := json.Unmarshal(data, &state); err != nil {
		t.Fatal(err)
	}
	// Simulate interruption after the last commit checkpoint but before the
	// final complete marker; replaying the layer would duplicate the commit.
	state["complete"] = false
	state["base"] = ""
	data, err = json.Marshal(state)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(recordPath, data, 0600); err != nil {
		t.Fatal(err)
	}
	result, err := s.Continue(ctx, "finish")
	if err != nil {
		t.Fatal(err)
	}
	if result.Head != p.Head || result.Base != p.Head {
		t.Fatalf("unexpected finalized state: %+v", result)
	}
}

func TestCompositionMutationLockAndExplicitStaleUnlock(t *testing.T) {
	ctx := context.Background()
	s, definitions, _, _, _ := conflictCompositionFixture(t)
	workspace := filepath.Join(t.TempDir(), "conflict")
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "locked", WorktreePath: workspace}); err == nil {
		t.Fatal("expected conflict")
	}
	lock := filepath.Join(definitions, ".git/layerctl/compositions/locked/lock")
	if err := os.WriteFile(lock, []byte("stale"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Continue(ctx, "locked"); err == nil || !strings.Contains(err.Error(), "projection unlock locked") {
		t.Fatalf("continue lock = %v", err)
	}
	if err := s.Delete(ctx, "locked"); err == nil || !strings.Contains(err.Error(), "locked") {
		t.Fatalf("delete lock = %v", err)
	}
	if err := s.Unlock(ctx, "locked"); err != nil {
		t.Fatal(err)
	}
	if err := s.Delete(ctx, "locked"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(workspace); !os.IsNotExist(err) {
		t.Fatalf("workspace remains after explicit cleanup: %v", err)
	}
}

func TestCompositionRecoversIncompleteReservationWithoutRecord(t *testing.T) {
	ctx := context.Background()
	root, s := compositionFixture(t)
	dir := filepath.Join(root, ".git/layerctl/compositions/interrupted")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "lock"), "stale")
	entries, err := s.List(ctx)
	if err != nil || len(entries) != 1 || entries[0].Name != "interrupted" {
		t.Fatalf("List=%v error=%v", entries, err)
	}
	if err := s.Delete(ctx, "interrupted"); err == nil || !strings.Contains(err.Error(), "locked") {
		t.Fatalf("Delete locked=%v", err)
	}
	if err := s.Unlock(ctx, "interrupted"); err != nil {
		t.Fatal(err)
	}
	if err := s.Delete(ctx, "interrupted"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatalf("reservation remains: %v", err)
	}
}

func TestCompositionIncompleteUnverifiedWorkspaceIsNeverDeleted(t *testing.T) {
	ctx := context.Background()
	root, s := compositionFixture(t)
	dir := filepath.Join(root, ".git/layerctl/compositions/interrupted")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	workspace := filepath.Join(t.TempDir(), "caller-workspace")
	if err := os.Mkdir(workspace, 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(workspace, "keep.txt"), "keep")
	record := map[string]any{"name": "interrupted", "workspace": workspace, "token": "expected", "through": "0001-x", "creating": true}
	data, err := json.Marshal(record)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "record.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "lock"), "stale")
	entries, err := s.List(ctx)
	if err != nil || len(entries) != 1 || entries[0].WorktreePath != workspace {
		t.Fatalf("List=%v error=%v", entries, err)
	}
	if err := s.Unlock(ctx, "interrupted"); err != nil {
		t.Fatal(err)
	}
	if err := s.Delete(ctx, "interrupted"); err == nil || !strings.Contains(err.Error(), "unverified incomplete workspace") {
		t.Fatalf("Delete=%v", err)
	}
	assertFile(t, filepath.Join(workspace, "keep.txt"), "keep")
	// Once the operator has inspected and removed the ambiguous path, the
	// remaining creation intent can be cleared without deleting user data.
	if err := os.RemoveAll(workspace); err != nil {
		t.Fatal(err)
	}
	if err := s.Delete(ctx, "interrupted"); err != nil {
		t.Fatal(err)
	}
}

func TestCompositionIncompleteVerifiedWorkspaceCanBeRemoved(t *testing.T) {
	ctx := context.Background()
	root, s := compositionFixture(t)
	dir := filepath.Join(root, ".git/layerctl/compositions/interrupted")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	workspace := filepath.Join(t.TempDir(), "workspace")
	if err := os.MkdirAll(filepath.Join(workspace, ".git"), 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(workspace, ".git/layerctl-owner"), "expected")
	writeFile(t, filepath.Join(workspace, "file.txt"), "created")
	record := map[string]any{"name": "interrupted", "workspace": workspace, "token": "expected", "through": "0001-x", "creating": true}
	data, err := json.Marshal(record)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "record.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
	if err := s.Delete(ctx, "interrupted"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(workspace); !os.IsNotExist(err) {
		t.Fatalf("verified owned workspace remains: %v", err)
	}
}

func TestCompositionIncompleteReservationPreservesUnknownDirectory(t *testing.T) {
	ctx := context.Background()
	root, s := compositionFixture(t)
	dir := filepath.Join(root, ".git/layerctl/compositions/interrupted")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "workspace/keep.txt"), "keep")
	if err := s.Delete(ctx, "interrupted"); err == nil || !strings.Contains(err.Error(), "unknown entry") {
		t.Fatalf("Delete=%v", err)
	}
	assertFile(t, filepath.Join(dir, "workspace/keep.txt"), "keep")
}

func TestCompositionScriptFailureIsNeverAutomaticallyReplayed(t *testing.T) {
	ctx := context.Background()
	_, s := compositionFixture(t)
	scriptDir := t.TempDir()
	script := filepath.Join(scriptDir, "run.sh")
	marker := filepath.Join(t.TempDir(), "external-marker")
	t.Setenv("LAYERCTL_TEST_MARKER", marker)
	if err := os.WriteFile(script, []byte("#!/bin/sh\nprintf 'ran\\n' >> \"$LAYERCTL_TEST_MARKER\"\nexit 1\n"), 0755); err != nil {
		t.Fatal(err)
	}
	s.Definition.Layers = []definition.Unit{{ID: "0001-script", Directory: scriptDir, Message: []byte("Script\n"), Operations: []definition.Operation{{Kind: "script", Path: script}}}}
	workspace := filepath.Join(t.TempDir(), "workspace")
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "script-failed", WorktreePath: workspace}); err == nil || !strings.Contains(err.Error(), "delete the projection") {
		t.Fatalf("failed script = %v", err)
	}
	if _, err := s.Continue(ctx, "script-failed"); err == nil || !strings.Contains(err.Error(), "uncertain") {
		t.Fatalf("continue failed script = %v", err)
	}
	assertFile(t, marker, "ran\n")
	if err := s.Delete(ctx, "script-failed"); err != nil {
		t.Fatal(err)
	}
}

func TestCompositionRejectsChangedPendingScript(t *testing.T) {
	ctx := context.Background()
	s, _, _, _, _ := conflictCompositionFixture(t)
	scriptDir := t.TempDir()
	script := filepath.Join(scriptDir, "run.sh")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nexit 0\n"), 0755); err != nil {
		t.Fatal(err)
	}
	s.Definition.Layers[0].Directory = scriptDir
	s.Definition.Layers[0].Operations = append(s.Definition.Layers[0].Operations, definition.Operation{Kind: "script", Path: script, Args: []string{"first"}})
	workspace := filepath.Join(t.TempDir(), "workspace")
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "script-changed", WorktreePath: workspace}); err == nil {
		t.Fatal("expected earlier patch conflict")
	}
	if err := os.WriteFile(script, []byte("#!/bin/sh\nexit 1\n"), 0755); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Continue(ctx, "script-changed"); err == nil || !strings.Contains(err.Error(), "definitions changed") {
		t.Fatalf("continue changed script = %v", err)
	}
}

func TestCompositionContinueRejectsChangedCoAuthors(t *testing.T) {
	ctx := context.Background()
	s, _, _, _, _ := conflictCompositionFixture(t)
	s.Definition.Layers[0].CoAuthors = []string{"Original <original@example.invalid>"}
	workspace := filepath.Join(t.TempDir(), "workspace")
	if _, err := s.Create(ctx, projection.CreateRequest{Name: "coauthors-changed", WorktreePath: workspace}); err == nil {
		t.Fatal("expected earlier patch conflict")
	}
	s.Definition.Layers[0].CoAuthors = []string{"Different <different@example.invalid>"}
	if _, err := s.Continue(ctx, "coauthors-changed"); err == nil || !strings.Contains(err.Error(), "definitions changed") {
		t.Fatalf("continue changed coauthors = %v", err)
	}
}

func TestCompositionRejectsChangedScriptSupportingFiles(t *testing.T) {
	for _, change := range []struct {
		name   string
		mutate func(*testing.T, string)
	}{
		{"content", func(t *testing.T, dir string) { writeFile(t, filepath.Join(dir, "asset.txt"), "changed\n") }},
		{"mode", func(t *testing.T, dir string) {
			if err := os.Chmod(filepath.Join(dir, "asset.txt"), 0755); err != nil {
				t.Fatal(err)
			}
		}},
		{"path", func(t *testing.T, dir string) {
			if err := os.Rename(filepath.Join(dir, "asset.txt"), filepath.Join(dir, "renamed.txt")); err != nil {
				t.Fatal(err)
			}
		}},
		{"symlink target", func(t *testing.T, dir string) {
			p := filepath.Join(dir, "asset-link")
			if err := os.Remove(p); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink("different.txt", p); err != nil {
				t.Fatal(err)
			}
		}},
	} {
		t.Run(change.name, func(t *testing.T) {
			ctx := context.Background()
			s, _, _, _, _ := conflictCompositionFixture(t)
			dir := t.TempDir()
			script := filepath.Join(dir, "run.sh")
			if err := os.WriteFile(script, []byte("#!/bin/sh\nexit 0\n"), 0755); err != nil {
				t.Fatal(err)
			}
			writeFile(t, filepath.Join(dir, "asset.txt"), "original\n")
			if err := os.Symlink("asset.txt", filepath.Join(dir, "asset-link")); err != nil {
				t.Fatal(err)
			}
			s.Definition.Layers[0].Directory = dir
			s.Definition.Layers[0].Operations = append(s.Definition.Layers[0].Operations, definition.Operation{Kind: "script", Path: script})
			workspace := filepath.Join(t.TempDir(), "workspace")
			if _, err := s.Create(ctx, projection.CreateRequest{Name: "asset-changed", WorktreePath: workspace}); err == nil {
				t.Fatal("expected earlier patch conflict")
			}
			change.mutate(t, dir)
			if _, err := s.Continue(ctx, "asset-changed"); err == nil || !strings.Contains(err.Error(), "definitions changed") {
				t.Fatalf("continue after changing %s = %v", change.name, err)
			}
			if _, err := os.Stat(filepath.Join(workspace, "vendor/after.txt")); !os.IsNotExist(err) {
				t.Fatalf("later operation ran: %v", err)
			}
		})
	}
}

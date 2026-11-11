package layer_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/layer"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
)

func TestAddCompositionSkipsDisabledPredecessor(t *testing.T) {
	root, _, _, composer := refreshCompositionFixture(t)
	disabled := filepath.Join(root, "layers", "0002-disabled", "layer.toml")
	writeFile(t, disabled, "[layer]\nenabled = false\n[vcs]\ncommit-msg = \"Disabled\\n\"\n", 0644)
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	service := &layer.Service{Definition: canonical, Git: &gitrepo.Repository{Root: root}, Projection: composer}
	workspace := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: workspace}); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(workspace, "file.txt"), "captured edit\n", 0644)
	writeFile(t, filepath.Join(workspace, "added.txt"), "new file\n", 0644)
	gitRun(t, workspace, "add", "-A")
	gitRun(t, workspace, "commit", "-qm", "Capture edits")
	wantTree := gitOutput(t, workspace, "rev-parse", "HEAD^{tree}")
	if err := service.Add(t.Context(), layer.AddRequest{ID: "0003-captured", Projection: "edit"}); err != nil {
		t.Fatalf("Add after disabled predecessor: %v", err)
	}
	canonical, err = definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	result, err := composer.Create(t.Context(), projection.CreateRequest{Name: "verify"})
	if err != nil {
		t.Fatal(err)
	}
	if got := gitOutput(t, result.WorktreePath, "rev-parse", "HEAD^{tree}"); got != wantTree {
		t.Fatalf("captured tree = %s, want %s", got, wantTree)
	}
	if got := gitOutput(t, result.WorktreePath, "show", "-s", "--format=%s", "HEAD"); got != "Capture edits" {
		t.Fatalf("captured commit message = %q", got)
	}
	if !canonical.Layers[1].Disabled {
		t.Fatal("disabled predecessor was changed")
	}
}

func TestAddCompositionRejectsMergeAncestry(t *testing.T) {
	root, _, service, composer := refreshCompositionFixture(t)
	workspace := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: workspace}); err != nil {
		t.Fatal(err)
	}
	other := filepath.Join(t.TempDir(), "other")
	if err := os.Mkdir(other, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, other, "init", "-q")
	writeFile(t, filepath.Join(other, "other.txt"), "other repository\n", 0644)
	gitRun(t, other, "add", ".")
	gitRun(t, other, "commit", "-qm", "Other source")
	gitRun(t, workspace, "fetch", "--", other, "HEAD")
	gitRun(t, workspace, "merge", "--allow-unrelated-histories", "-qm", "Import other", "FETCH_HEAD")
	// A later linear commit must not hide the merge within the captured range.
	writeFile(t, filepath.Join(workspace, "after.txt"), "after merge\n", 0644)
	gitRun(t, workspace, "add", ".")
	gitRun(t, workspace, "commit", "-qm", "After merge")
	originalHead := gitOutput(t, workspace, "rev-parse", "HEAD")
	originalManifest := readFile(t, filepath.Join(root, "layers", "0001-source", "layer.toml"))
	err := service.Add(t.Context(), layer.AddRequest{ID: "0002-merged", Projection: "edit"})
	if err == nil || !strings.Contains(err.Error(), "merge") || !strings.Contains(err.Error(), "git-clone") {
		t.Fatalf("Add with merged source = %v, want clear ancestry rejection", err)
	}
	if _, err := os.Stat(filepath.Join(root, "layers", "0002-merged")); !os.IsNotExist(err) {
		t.Fatalf("rejected capture created a layer: %v", err)
	}
	if got := gitOutput(t, workspace, "rev-parse", "HEAD"); got != originalHead {
		t.Fatalf("workspace HEAD changed from %s to %s", originalHead, got)
	}
	if got := readFile(t, filepath.Join(root, "layers", "0001-source", "layer.toml")); got != originalManifest {
		t.Fatal("existing layer changed after rejected capture")
	}
}

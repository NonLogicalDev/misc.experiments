package layer_test

import (
	"bytes"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/layer"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
)

func TestRefreshCompositionPreservesClonePreCheckoutPatch(t *testing.T) {
	for key, value := range map[string]string{"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"} {
		t.Setenv(key, value)
	}
	source := filepath.Join(t.TempDir(), "source")
	if err := os.Mkdir(source, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, source, "init", "-q")
	writeFile(t, filepath.Join(source, "file.txt"), "original\n", 0644)
	gitRun(t, source, "add", ".")
	gitRun(t, source, "commit", "-qm", "source")
	sourceCommit := gitOutput(t, source, "rev-parse", "HEAD")
	writeFile(t, filepath.Join(source, "file.txt"), "prepared\n", 0644)
	sourceGit := &gitrepo.Repository{Root: source}
	patch, err := sourceGit.Bytes(t.Context(), source, "diff", "--binary", "--full-index")
	if err != nil {
		t.Fatal(err)
	}
	if len(patch) == 0 {
		t.Fatal("expected pre-checkout patch")
	}
	gitRun(t, source, "add", "file.txt")
	preparedTree := gitOutput(t, source, "write-tree")
	gitRun(t, source, "reset", "--hard", "-q", sourceCommit)

	root := filepath.Join(t.TempDir(), "definitions")
	if err := os.Mkdir(root, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, root, "init", "-q")
	layerDir := filepath.Join(root, "layers", "0001-source")
	patchPath := filepath.Join(layerDir, "prepare.patch")
	writeFile(t, patchPath, string(patch), 0644)
	writeFile(t, filepath.Join(layerDir, "layer.toml"), fmt.Sprintf("[vcs]\ncommit-msg = \"Import\\n\"\n[[operation]]\n[operation.git-clone]\nurl = %q\ndir = \"\"\npre-checkout-patch = \"prepare.patch\"\n", source), 0644)
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	git := &gitrepo.Repository{Root: root}
	composer := &projection.CompositionService{Definition: canonical, Git: git, Log: log.New(io.Discard, "", 0)}
	service := &layer.Service{Definition: canonical, Git: git, Projection: composer}
	workspace := filepath.Join(t.TempDir(), "workspace")
	made, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: workspace, Through: "0001-source"})
	if err != nil {
		t.Fatal(err)
	}
	defer composer.Delete(t.Context(), "edit")
	if got := gitOutput(t, workspace, "rev-parse", "HEAD^{tree}"); got != preparedTree {
		t.Fatalf("prepared tree = %s, want %s", got, preparedTree)
	}
	if got := readFile(t, filepath.Join(workspace, "file.txt")); got != "prepared\n" {
		t.Fatalf("prepared file = %q", got)
	}
	if got := strings.Fields(gitOutput(t, workspace, "show", "-s", "--format=%P", "HEAD")); len(got) != 1 || got[0] != sourceCommit {
		t.Fatalf("imported parents = %v", got)
	}
	if made.Base != made.Head {
		t.Fatal("new projection does not start at its base")
	}
	writeFile(t, filepath.Join(workspace, "file.txt"), "prepared and edited\n", 0644)
	gitRun(t, workspace, "add", "-A")
	gitRun(t, workspace, "commit", "-qm", "Edit prepared tree")
	wantTree := gitOutput(t, workspace, "rev-parse", "HEAD^{tree}")
	if err := service.RefreshComposition(t.Context(), "0001-source", "edit", composer); err != nil {
		t.Fatal(err)
	}
	unit, err := definition.LoadUnit("0001-source", layerDir)
	if err != nil {
		t.Fatal(err)
	}
	if len(unit.Operations) != 2 || unit.Operations[0].Kind != "git-clone" || unit.Operations[0].PreCheckoutPatch != patchPath || unit.Operations[1].Kind != "patch" {
		t.Fatalf("operations = %#v", unit.Operations)
	}
	actualPatch, err := os.ReadFile(patchPath)
	if err != nil || !bytes.Equal(actualPatch, patch) {
		t.Fatalf("pre-checkout patch changed: %v", err)
	}
	canonical, err = definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	replay, err := composer.Create(t.Context(), projection.CreateRequest{Name: "verify", Through: "0001-source"})
	if err != nil {
		t.Fatal(err)
	}
	defer composer.Delete(t.Context(), "verify")
	if got := gitOutput(t, replay.WorktreePath, "rev-parse", "HEAD^{tree}"); got != wantTree {
		t.Fatalf("replayed tree = %s, want %s", got, wantTree)
	}
	if got := strings.Fields(gitOutput(t, replay.WorktreePath, "show", "-s", "--format=%P", "HEAD")); len(got) != 1 || got[0] != sourceCommit {
		t.Fatalf("replayed parents = %v", got)
	}
	if got := gitOutput(t, replay.WorktreePath, "show", "-s", "--format=%B", "HEAD"); got != "Edit prepared tree" {
		t.Fatalf("replayed message = %q", got)
	}
	if got := readFile(t, filepath.Join(source, "file.txt")); got != "original\n" {
		t.Fatalf("source changed: %q", got)
	}
}

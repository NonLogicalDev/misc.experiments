package layer_test

import (
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

func TestRefreshCompositionPreservesClonePreCheckoutScript(t *testing.T) {
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
	writeFile(t, filepath.Join(source, "file.txt"), "prepatched\n", 0644)
	sourceGit := &gitrepo.Repository{Root: source}
	patch, err := sourceGit.Bytes(t.Context(), source, "diff", "--binary", "--full-index")
	if err != nil || len(patch) == 0 {
		t.Fatalf("generate pre-checkout patch: %v", err)
	}
	gitRun(t, source, "reset", "--hard", "-q", sourceCommit)

	root := filepath.Join(t.TempDir(), "definitions")
	if err := os.Mkdir(root, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, root, "init", "-q")
	layerDir := filepath.Join(root, "layers", "0001-source")
	writeFile(t, filepath.Join(layerDir, "prepare.patch"), string(patch), 0644)
	writeFile(t, filepath.Join(layerDir, "support.txt"), "script output\n", 0644)
	hook := filepath.Join(layerDir, "prepare.sh")
	writeFile(t, hook, `#!/bin/sh
set -eu
test "$(git rev-parse --is-bare-repository)" = true
test "$(git show :file.txt)" = prepatched
test "$LAYERCTL_LAYER_ID" = 0001-source
test "$LAYERCTL_OPERATION_INDEX" = 1
blob=$(git hash-object -w --stdin < "$LAYERCTL_LAYER_DIR/support.txt")
git update-index --add --cacheinfo "100644,$blob,generated.txt"
git write-tree
`, 0755)
	writeFile(t, filepath.Join(layerDir, "layer.toml"), fmt.Sprintf("[vcs]\ncommit-msg = \"Import\\n\"\n[[operation]]\n[operation.git-clone]\nurl = %q\npre-checkout-patch = \"prepare.patch\"\npre-checkout-script = \"prepare.sh\"\n", source), 0644)
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	git := &gitrepo.Repository{Root: root}
	composer := &projection.CompositionService{Definition: canonical, Git: git, Log: log.New(io.Discard, "", 0)}
	service := &layer.Service{Definition: canonical, Git: git, Projection: composer}
	workspace := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: workspace, Through: "0001-source"}); err != nil {
		t.Fatal(err)
	}
	defer composer.Delete(t.Context(), "edit")
	if got := readFile(t, filepath.Join(workspace, "generated.txt")); got != "script output\n" {
		t.Fatalf("generated file = %q", got)
	}
	if got := strings.Fields(gitOutput(t, workspace, "show", "-s", "--format=%P", "HEAD")); len(got) != 1 || got[0] != sourceCommit {
		t.Fatalf("imported parents = %v", got)
	}
	writeFile(t, filepath.Join(workspace, "file.txt"), "edited\n", 0644)
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
	if unit.Operations[0].PreCheckoutScript != hook || unit.Operations[0].Dir != "" {
		t.Fatalf("clone operation = %#v", unit.Operations[0])
	}
	if got := readFile(t, filepath.Join(layerDir, "support.txt")); got != "script output\n" {
		t.Fatalf("support file = %q", got)
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
}

func TestClonePreCheckoutScriptRejectsSymlinkAfterDefinitionLoad(t *testing.T) {
	for key, value := range map[string]string{"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"} {
		t.Setenv(key, value)
	}
	source := filepath.Join(t.TempDir(), "source")
	if err := os.Mkdir(source, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, source, "init", "-q")
	writeFile(t, filepath.Join(source, "file"), "source\n", 0644)
	gitRun(t, source, "add", ".")
	gitRun(t, source, "commit", "-qm", "source")
	root := filepath.Join(t.TempDir(), "definitions")
	if err := os.Mkdir(root, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, root, "init", "-q")
	layerDir := filepath.Join(root, "layers", "0001-source")
	hook := filepath.Join(layerDir, "prepare.sh")
	writeFile(t, hook, "#!/bin/sh\ngit write-tree\n", 0755)
	writeFile(t, filepath.Join(layerDir, "layer.toml"), fmt.Sprintf("[vcs]\ncommit-msg = 'Import'\n[[operation]]\n[operation.git-clone]\nurl = %q\npre-checkout-script = 'prepare.sh'\n", source), 0644)
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(t.TempDir(), "executed")
	t.Setenv("LAYERCTL_TEST_MARKER", marker)
	outside := filepath.Join(t.TempDir(), "outside.sh")
	writeFile(t, outside, "#!/bin/sh\ntouch \"$LAYERCTL_TEST_MARKER\"\ngit write-tree\n", 0755)
	if err := os.Remove(hook); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, hook); err != nil {
		t.Fatal(err)
	}
	git := &gitrepo.Repository{Root: root}
	composer := &projection.CompositionService{Definition: canonical, Git: git, Log: log.New(io.Discard, "", 0)}
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "test"}); err == nil {
		t.Fatal("accepted a script replaced by a symlink")
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("outside script was executed: %v", err)
	}
}

func TestRefreshRejectsChangingPreCheckoutCommitWithoutChangingLayer(t *testing.T) {
	for key, value := range map[string]string{"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"} {
		t.Setenv(key, value)
	}
	source := filepath.Join(t.TempDir(), "source")
	if err := os.Mkdir(source, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, source, "init", "-q")
	writeFile(t, filepath.Join(source, "file"), "source\n", 0644)
	gitRun(t, source, "add", ".")
	gitRun(t, source, "commit", "-qm", "source")
	root := filepath.Join(t.TempDir(), "definitions")
	if err := os.Mkdir(root, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, root, "init", "-q")
	layerDir := filepath.Join(root, "layers", "0001-source")
	marker := filepath.Join(t.TempDir(), "already-ran")
	t.Setenv("LAYERCTL_TEST_COUNTER", marker)
	writeFile(t, filepath.Join(layerDir, "prepare.sh"), `#!/bin/sh
set -eu
if test -e "$LAYERCTL_TEST_COUNTER"; then
  GIT_AUTHOR_DATE='2001-01-02T00:00:00Z'; GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"
else
  : > "$LAYERCTL_TEST_COUNTER"
  GIT_AUTHOR_DATE='2001-01-01T00:00:00Z'; GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"
fi
export GIT_AUTHOR_DATE GIT_COMMITTER_DATE
git commit-tree "$(git write-tree)" -p "$LAYERCTL_SOURCE_COMMIT" -m prepared
`, 0755)
	manifest := filepath.Join(layerDir, "layer.toml")
	writeFile(t, manifest, fmt.Sprintf("[vcs]\ncommit-msg = 'Import'\n[[operation]]\n[operation.git-clone]\nurl = %q\npre-checkout-script = 'prepare.sh'\n", source), 0644)
	before := readFile(t, manifest)
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	git := &gitrepo.Repository{Root: root}
	composer := &projection.CompositionService{Definition: canonical, Git: git, Log: log.New(io.Discard, "", 0)}
	service := &layer.Service{Definition: canonical, Git: git, Projection: composer}
	workspace := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: workspace, Through: "0001-source"}); err != nil {
		t.Fatal(err)
	}
	defer composer.Delete(t.Context(), "edit")
	writeFile(t, filepath.Join(workspace, "file"), "edited\n", 0644)
	gitRun(t, workspace, "add", "-A")
	gitRun(t, workspace, "commit", "-qm", "Edit file")
	if err := service.RefreshComposition(t.Context(), "0001-source", "edit", composer); err == nil || !strings.Contains(err.Error(), "ancestry") {
		t.Fatalf("refresh error = %v, want changed ancestry", err)
	}
	if got := readFile(t, manifest); got != before {
		t.Fatalf("failed refresh changed manifest: %q", got)
	}
}

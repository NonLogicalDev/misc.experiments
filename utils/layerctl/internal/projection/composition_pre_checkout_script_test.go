package projection_test

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
)

func TestCompositionPreCheckoutScriptFailureWithConflictsIsUncertain(t *testing.T) {
	ctx := context.Background()
	_, service := compositionFixture(t)
	source, _ := sourceFixture(t, "source.txt", "source\n")
	dir := t.TempDir()
	script := filepath.Join(dir, "prepare.sh")
	marker := filepath.Join(t.TempDir(), "side-effect")
	t.Setenv("LAYERCTL_TEST_SIDE_EFFECT", marker)
	writeFile(t, script, `#!/bin/sh
set -eu
printf 'ran\n' >> "$LAYERCTL_TEST_SIDE_EFFECT"
(
  unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE GIT_COMMON_DIR
  blob=$(printf conflict | git -C "$LAYERCTL_WORKTREE_DIR" hash-object -w --stdin)
  printf '100644 %s 1\tconflict.txt\n100644 %s 2\tconflict.txt\n100644 %s 3\tconflict.txt\n' "$blob" "$blob" "$blob" |
    git -C "$LAYERCTL_WORKTREE_DIR" update-index --index-info
)
exit 1
`)
	if err := os.Chmod(script, 0755); err != nil {
		t.Fatal(err)
	}
	service.Definition.Layers = []definition.Unit{{ID: "0001-source", Directory: dir, Message: []byte("Import\n"), Operations: []definition.Operation{{Kind: "git-clone", URL: source, PreCheckoutScript: script}}}}
	workspace := filepath.Join(t.TempDir(), "workspace")
	_, err := service.Create(ctx, projection.CreateRequest{Name: "failed-hook", WorktreePath: workspace})
	if err == nil || !strings.Contains(err.Error(), "delete the projection") {
		t.Fatalf("Create error = %v", err)
	}
	var conflict *projection.CompositionConflictError
	if errors.As(err, &conflict) {
		t.Fatalf("script failure exposed as resumable conflict: %v", err)
	}
	assertFile(t, marker, "ran\n")
	unmerged := gitOutput(t, workspace, "ls-files", "--unmerged")
	for _, stage := range []string{" 1\tconflict.txt", " 2\tconflict.txt", " 3\tconflict.txt"} {
		if !strings.Contains(unmerged, stage) {
			t.Fatalf("missing unmerged stage %q in %q", stage, unmerged)
		}
	}
	if _, err := exec.Command("git", "-C", workspace, "rev-parse", "--verify", "HEAD^{commit}").CombinedOutput(); err == nil {
		t.Fatal("failed clone created a layer commit")
	}
	if _, err := service.Continue(ctx, "failed-hook"); err == nil || !strings.Contains(err.Error(), "uncertain") {
		t.Fatalf("Continue error = %v", err)
	}
	assertFile(t, marker, "ran\n")
	if _, err := exec.Command("git", "-C", workspace, "rev-parse", "--verify", "HEAD^{commit}").CombinedOutput(); err == nil {
		t.Fatal("Continue created a layer commit")
	}
	if err := service.Delete(ctx, "failed-hook"); err != nil {
		t.Fatal(err)
	}
}

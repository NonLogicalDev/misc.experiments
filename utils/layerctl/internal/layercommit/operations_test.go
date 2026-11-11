package layercommit_test

import (
	"bytes"
	"os/exec"
	"path/filepath"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/layercommit"
)

// Each patch is a real binary-safe Git diff between successive committed trees.
// The test reuses the second patch after applying its inverse, then edits a file
// supplied by the overlay. This distinguishes sequential execution from batching.
func TestManifestOperationsApplyInOrderAndMakeOneCommit(t *testing.T) {
	root, base := newRepository(t)
	change := func(path, content, message string) string {
		t.Helper()
		writeFile(t, filepath.Join(root, path), []byte(content), 0o644)
		gitRun(t, root, "add", path)
		gitRun(t, root, "commit", "-m", message)
		return gitOutput(t, root, "rev-parse", "HEAD")
	}
	first := change("text.txt", "first\n", "first")
	second := change("text.txt", "second\n", "second")
	added := change("added.txt", "overlay original\n", "overlay")
	last := change("added.txt", "overlay edited\n", "overlay change")

	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "one.patch"), operationDiff(t, root, base, first, "text.txt"), 0o644)
	writeFile(t, filepath.Join(dir, "two.patch"), operationDiff(t, root, first, second, "text.txt"), 0o644)
	writeFile(t, filepath.Join(dir, "reverse.patch"), operationDiff(t, root, second, first, "text.txt"), 0o644)
	writeFile(t, filepath.Join(dir, "four.patch"), operationDiff(t, root, added, last, "added.txt"), 0o644)
	writeFile(t, filepath.Join(dir, "files", "added.txt"), []byte("overlay original\n"), 0o644)
	message := "Ordered changes\n\nDetails stay intact.\n\n"
	manifest := `[vcs]
commit-msg = "Ordered changes\n\nDetails stay intact.\n\n"
[[operation]]
[operation.patch]
file = "one.patch"
[[operation]]
[operation.patch]
file = "two.patch"
[[operation]]
[operation.patch]
file = "reverse.patch"
[[operation]]
[operation.patch]
file = "two.patch"
[[operation]]
[operation.overlay]
directory = "files"
[[operation]]
[operation.patch]
file = "four.patch"
`
	writeFile(t, filepath.Join(dir, "layer.toml"), []byte(manifest), 0o644)
	unit, err := definition.LoadUnit("0001-ordered", dir)
	if err != nil {
		t.Fatalf("LoadUnit() error = %v", err)
	}
	gitRun(t, root, "switch", "--detach", base)
	git, err := gitrepo.Discover(t.Context(), root)
	if err != nil {
		t.Fatal(err)
	}
	service := &layercommit.Service{Git: git}
	if err := service.Apply(t.Context(), root, unit); err != nil {
		t.Fatalf("Apply() error = %v", err)
	}
	if got := gitOutput(t, root, "rev-parse", "HEAD^"); got != base {
		t.Fatalf("parent = %q, want %q (all operations must create one commit)", got, base)
	}
	if got := string(gitBytes(t, root, "show", "HEAD:text.txt")); got != "second\n" {
		t.Fatalf("text.txt = %q, want second", got)
	}
	if got := string(gitBytes(t, root, "show", "HEAD:added.txt")); got != "overlay edited\n" {
		t.Fatalf("added.txt = %q, want overlay edited", got)
	}
	commit := gitBytes(t, root, "cat-file", "commit", "HEAD")
	_, gotMessage, ok := bytes.Cut(commit, []byte("\n\n"))
	if !ok || string(gotMessage) != message {
		t.Fatalf("commit message = %q, want %q", gotMessage, message)
	}
}

// A patch that requires a prior operation must not be committed when placed
// before it. The later patch cannot be treated as implicitly already applied.
func TestManifestOperationsDoNotSkipFailedEarlierPatch(t *testing.T) {
	root, base := newRepository(t)
	writeFile(t, filepath.Join(root, "text.txt"), []byte("first\n"), 0o644)
	gitRun(t, root, "add", "text.txt")
	gitRun(t, root, "commit", "-m", "first")
	first := gitOutput(t, root, "rev-parse", "HEAD")
	writeFile(t, filepath.Join(root, "text.txt"), []byte("second\n"), 0o644)
	gitRun(t, root, "add", "text.txt")
	gitRun(t, root, "commit", "-m", "second")
	second := gitOutput(t, root, "rev-parse", "HEAD")
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "one.patch"), operationDiff(t, root, base, first, "text.txt"), 0o644)
	writeFile(t, filepath.Join(dir, "two.patch"), operationDiff(t, root, first, second, "text.txt"), 0o644)
	manifest := `[vcs]
commit-msg = "Reversed\n"
[[operation]]
[operation.patch]
file = "two.patch"
[[operation]]
[operation.patch]
file = "one.patch"
`
	writeFile(t, filepath.Join(dir, "layer.toml"), []byte(manifest), 0o644)
	unit, err := definition.LoadUnit("0001-reversed", dir)
	if err != nil {
		t.Fatalf("LoadUnit() error = %v", err)
	}
	gitRun(t, root, "switch", "--detach", base)
	git, err := gitrepo.Discover(t.Context(), root)
	if err != nil {
		t.Fatal(err)
	}
	if err := (&layercommit.Service{Git: git}).Apply(t.Context(), root, unit); err == nil {
		t.Fatal("Apply() accepted a patch before its required predecessor")
	}
	if got := gitOutput(t, root, "rev-parse", "HEAD"); got != base {
		t.Fatalf("failed sequence committed %q; want HEAD %q", got, base)
	}
}

func operationDiff(t *testing.T, root, before, after, file string) []byte {
	t.Helper()
	patch := gitBytes(t, root, "diff", "--binary", "--full-index", before, after, "--", file)
	if len(patch) == 0 {
		t.Fatal("fixture patch is empty")
	}
	return patch
}

func gitBytes(t *testing.T, directory string, args ...string) []byte {
	t.Helper()
	cmd := exec.CommandContext(t.Context(), "git", args...)
	cmd.Dir = directory
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	result, err := cmd.Output()
	if err != nil {
		t.Fatalf("git %v: %v: %s", args, err, &stderr)
	}
	return result
}

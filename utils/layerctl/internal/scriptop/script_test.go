package scriptop_test

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/scriptop"
)

func runGit(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v: %s", args, err, out)
	}
	return string(out)
}
func workspace(t *testing.T) string {
	t.Helper()
	w := t.TempDir()
	runGit(t, w, "init", "-q")
	runGit(t, w, "config", "user.name", "Test")
	runGit(t, w, "config", "user.email", "test@example.invalid")
	if err := os.WriteFile(filepath.Join(w, "tracked"), []byte("before\n"), 0644); err != nil {
		t.Fatal(err)
	}
	runGit(t, w, "add", ".")
	runGit(t, w, "commit", "-qm", "base")
	return w
}
func TestRunPassesArgumentsContextAndStagesChanges(t *testing.T) {
	w := workspace(t)
	dir := t.TempDir()
	script := filepath.Join(dir, "run.sh")
	code := `#!/bin/sh
printf '%s\n' "$1" "$2" "$LAYERCTL_WORKTREE_DIR" "$LAYERCTL_DEFINITION_DIR" "$LAYERCTL_LAYER_DIR" "$LAYERCTL_LAYER_ID" "$LAYERCTL_OPERATION_INDEX" > result
pwd -P > location
printf changed > tracked
`
	if err := os.WriteFile(script, []byte(code), 0755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("LAYERCTL_LAYER_ID", "old-value")
	op := definition.Operation{Kind: "script", Path: script, Args: []string{"hello world", "$(not executed)"}}
	if err := scriptop.Run(context.Background(), w, "/definitions", "0003-test", dir, 2, op); err != nil {
		t.Fatal(err)
	}
	result, err := os.ReadFile(filepath.Join(w, "result"))
	if err != nil {
		t.Fatal(err)
	}
	want := strings.Join([]string{"hello world", "$(not executed)", w, "/definitions", dir, "0003-test", "3", ""}, "\n")
	if string(result) != want {
		t.Fatalf("result = %q, want %q", result, want)
	}
	cwd, err := os.ReadFile(filepath.Join(w, "location"))
	if err != nil {
		t.Fatal(err)
	}
	real, err := filepath.EvalSymlinks(w)
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(string(cwd)) != real {
		t.Fatalf("cwd = %q, want %q", cwd, real)
	}
	staged := runGit(t, w, "diff", "--cached", "--name-only")
	for _, name := range []string{"location", "result", "tracked"} {
		if !strings.Contains(staged, name+"\n") {
			t.Errorf("missing staged file %s: %q", name, staged)
		}
	}
}
func TestFailureDoesNotStageChanges(t *testing.T) {
	w := workspace(t)
	dir := t.TempDir()
	script := filepath.Join(dir, "fail.sh")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nprintf changed > tracked\nexit 9\n"), 0755); err != nil {
		t.Fatal(err)
	}
	err := scriptop.Run(context.Background(), w, "/definitions", "0001-test", dir, 0, definition.Operation{Kind: "script", Path: script})
	if err == nil {
		t.Fatal("expected script failure")
	}
	if got := runGit(t, w, "diff", "--cached", "--name-only"); got != "" {
		t.Fatalf("failed script staged %q", got)
	}
	if got, err := os.ReadFile(filepath.Join(w, "tracked")); err != nil || string(got) != "changed" {
		t.Fatalf("worktree effect missing: %q %v", got, err)
	}
}
func TestRejectsUnsafeScriptPaths(t *testing.T) {
	w := workspace(t)
	dir := t.TempDir()
	outside := filepath.Join(t.TempDir(), "outside")
	if err := os.WriteFile(outside, []byte("#!/bin/sh\nexit 0\n"), 0755); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "link")
	if err := os.Symlink(outside, link); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{outside, link} {
		err := scriptop.Run(context.Background(), w, "/definitions", "0001-test", dir, 0, definition.Operation{Kind: "script", Path: path})
		if err == nil {
			t.Fatalf("accepted unsafe script %q", path)
		}
	}
}

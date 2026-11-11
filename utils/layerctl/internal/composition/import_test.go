package composition_test

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/composition"
)

func git(t *testing.T, dir string, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("git %v: %v: %s", args, err, out)
	}
	return strings.TrimSpace(string(out))
}
func repo(t *testing.T) string {
	t.Helper()
	p := t.TempDir()
	git(t, p, "init", "-q")
	git(t, p, "config", "user.name", "Tester")
	git(t, p, "config", "user.email", "test@example.invalid")
	return p
}
func write(t *testing.T, root, path, text string, mode os.FileMode) {
	t.Helper()
	p := filepath.Join(root, path)
	if err := os.MkdirAll(filepath.Dir(p), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(text), mode); err != nil {
		t.Fatal(err)
	}
}
func commit(t *testing.T, root, label string) string {
	t.Helper()
	git(t, root, "add", "-A")
	git(t, root, "commit", "-qm", label)
	return git(t, root, "rev-parse", "HEAD")
}
func fileURL(path string) string { return "file://" + path }
func TestImportRootAndNestedPreservesTreeAndAncestry(t *testing.T) {
	src := repo(t)
	write(t, src, ".gitattributes", "ignored.txt export-ignore\n", 0644)
	write(t, src, ".gitignore", "git-ignored.txt\n", 0644)
	write(t, src, "git-ignored.txt", "tracked despite ignore\n", 0644)
	git(t, src, "add", "-f", "git-ignored.txt")
	write(t, src, "ignored.txt", "retained\n", 0644)
	write(t, src, "run.sh", "#!/bin/sh\n", 0755)
	if err := os.Symlink("run.sh", filepath.Join(src, "link")); err != nil {
		t.Fatal(err)
	}
	first := commit(t, src, "first")
	write(t, src, "folder/file", "v2\n", 0644)
	second := commit(t, src, "second")
	work := repo(t)
	write(t, work, "already-staged.txt", "staged", 0644)
	git(t, work, "add", "already-staged.txt")
	write(t, work, "untracked.txt", "untracked", 0644)
	ctx := context.Background()
	got, err := composition.Import(ctx, work, composition.CloneRequest{URL: fileURL(src)})
	if err != nil {
		t.Fatal(err)
	}
	if got != second {
		t.Fatalf("commit %q want %q", got, second)
	}
	if got := git(t, work, "show", ":git-ignored.txt"); got != "tracked despite ignore" {
		t.Fatalf("ignored source not staged: %q", got)
	}
	if got := git(t, work, "show", ":already-staged.txt"); got != "staged" {
		t.Fatalf("prior staged data changed: %q", got)
	}
	if got := git(t, work, "ls-files", "--", "untracked.txt"); got != "" {
		t.Fatalf("unrelated untracked file staged: %q", got)
	}
	if got := git(t, work, "rev-list", "--count", second); got != "2" {
		t.Fatalf("ancestry count %s", got)
	}
	if git(t, work, "cat-file", "-t", first) != "commit" {
		t.Fatal("ancestor not imported")
	}
	if b, err := os.ReadFile(filepath.Join(work, "ignored.txt")); err != nil || string(b) != "retained\n" {
		t.Fatalf("tracked export-ignored file: %q %v", b, err)
	}
	if info, err := os.Stat(filepath.Join(work, "run.sh")); err != nil || info.Mode()&0111 == 0 {
		t.Fatalf("executable: %v %v", info, err)
	}
	if target, err := os.Readlink(filepath.Join(work, "link")); err != nil || target != "run.sh" {
		t.Fatalf("link: %q %v", target, err)
	}
	other := repo(t)
	write(t, other, "item", "nested\n", 0644)
	commit(t, other, "first")
	if _, err := composition.Import(ctx, work, composition.CloneRequest{URL: fileURL(other), Dir: "vendor/tool"}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(work, "vendor/tool/.git")); !os.IsNotExist(err) {
		t.Fatalf("nested metadata: %v", err)
	}
}
func TestImportRejectsCollisionAndUnsafeDestination(t *testing.T) {
	src := repo(t)
	write(t, src, "same", "from source", 0644)
	commit(t, src, "source")
	work := repo(t)
	write(t, work, "same", "preserve", 0644)
	if _, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: fileURL(src)}); err == nil {
		t.Fatal("collision accepted")
	}
	if b, _ := os.ReadFile(filepath.Join(work, "same")); string(b) != "preserve" {
		t.Fatalf("overwrote content %q", b)
	}
	for _, dir := range []string{"../escape", "/absolute", "a/.git/x", "a/../x"} {
		if _, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: fileURL(src), Dir: dir}); err == nil {
			t.Fatalf("accepted %q", dir)
		}
	}
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(work, "link")); err != nil {
		t.Fatal(err)
	}
	if _, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: fileURL(src), Dir: "link/sub"}); err == nil {
		t.Fatal("symlink parent accepted")
	}
	if _, err := os.Stat(filepath.Join(outside, "sub")); !os.IsNotExist(err) {
		t.Fatalf("outside mutated: %v", err)
	}
}
func TestImportRefCommitAndShallowOverlap(t *testing.T) {
	src := repo(t)
	write(t, src, "x", "1", 0644)
	one := commit(t, src, "one")
	write(t, src, "x", "2", 0644)
	two := commit(t, src, "two")
	write(t, src, "x", "3", 0644)
	tip := commit(t, src, "three")
	branch := git(t, src, "branch", "--show-current")
	work := repo(t)
	if got, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: fileURL(src), Dir: "old", Ref: branch, Commit: one}); err != nil || got != one {
		t.Fatalf("commit at ref: %s %v", got, err)
	}
	if _, err := composition.Import(context.Background(), repo(t), composition.CloneRequest{URL: fileURL(src), Ref: branch, Commit: one, Depth: 1}); err == nil || !strings.Contains(err.Error(), "shallow") {
		t.Fatalf("expected shallow unavailable: %v", err)
	}
	shallow := repo(t)
	if got, err := composition.Import(context.Background(), shallow, composition.CloneRequest{URL: fileURL(src), Dir: "first", Ref: branch, Depth: 2}); err != nil || got != tip {
		t.Fatalf("shallow import: %s %v", got, err)
	}
	if got := git(t, shallow, "rev-list", "--count", tip); got != "2" {
		t.Fatalf("shallow ancestry count %s", got)
	}
	if _, err := composition.Import(context.Background(), shallow, composition.CloneRequest{URL: fileURL(src), Dir: "second", Ref: branch, Commit: two}); err == nil || !strings.Contains(err.Error(), "overlapping") {
		t.Fatalf("expected overlapping shallow rejection: %v", err)
	}
	localShallow := repo(t)
	if got, err := composition.Import(context.Background(), localShallow, composition.CloneRequest{URL: src, Ref: branch, Depth: 1}); err != nil || got != tip {
		t.Fatalf("local shallow import: %s %v", got, err)
	}
	if got := git(t, localShallow, "rev-list", "--count", tip); got != "1" {
		t.Fatalf("local path depth ignored: %s", got)
	}
	if _, err := os.Stat(filepath.Join(shallow, "second")); !os.IsNotExist(err) {
		t.Fatalf("failed import created destination: %v", err)
	}
}

func TestImportDoesNotReplaceDeletedButStagedFile(t *testing.T) {
	src := repo(t)
	write(t, src, "same", "from source", 0644)
	commit(t, src, "source")
	work := repo(t)
	write(t, work, "same", "already staged", 0644)
	git(t, work, "add", "same")
	if err := os.Remove(filepath.Join(work, "same")); err != nil {
		t.Fatal(err)
	}
	if _, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: fileURL(src)}); err == nil || !strings.Contains(err.Error(), "index") {
		t.Fatalf("staged conflict not rejected: %v", err)
	}
	if got := git(t, work, "show", ":same"); got != "already staged" {
		t.Fatalf("index overwritten: %q", got)
	}
	if _, err := os.Stat(filepath.Join(work, "same")); !os.IsNotExist(err) {
		t.Fatalf("file recreated: %v", err)
	}
}

func TestImportRejectsSubmoduleBeforeWriting(t *testing.T) {
	src := repo(t)
	write(t, src, "regular.txt", "regular", 0644)
	head := commit(t, src, "base")
	git(t, src, "update-index", "--add", "--cacheinfo", "160000,"+head+",external")
	git(t, src, "commit", "-qm", "add gitlink")
	work := repo(t)
	if _, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: src, Dir: "copy"}); err == nil || !strings.Contains(err.Error(), "submodule") {
		t.Fatalf("submodule accepted: %v", err)
	}
	if _, err := os.Stat(filepath.Join(work, "copy")); !os.IsNotExist(err) {
		t.Fatalf("failed clone created files: %v", err)
	}
}

func TestImportDoesNotExposeSourceCredentialsInError(t *testing.T) {
	work := repo(t)
	secret := "unique-secret-for-test"
	_, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: "file://user:" + secret + "@invalid/repo"})
	if err == nil {
		t.Fatal("expected fetch to fail")
	}
	if strings.Contains(err.Error(), secret) {
		t.Fatalf("error exposed credentials: %v", err)
	}
}

func TestImportAllowsSubsequentThreeWayPatch(t *testing.T) {
	src := repo(t)
	write(t, src, "file.txt", "before\n", 0644)
	base := commit(t, src, "base")
	write(t, src, "file.txt", "after\n", 0644)
	after := commit(t, src, "after")
	patchCmd := exec.Command("git", "diff", "--binary", "--full-index", base, after)
	patchCmd.Dir = src
	patch, err := patchCmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	work := repo(t)
	if _, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: src, Commit: base}); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("git", "apply", "--3way", "--index", "-")
	cmd.Dir = work
	cmd.Stdin = strings.NewReader(string(patch))
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("apply after import: %v: %s", err, out)
	}
	if got := git(t, work, "show", ":file.txt"); got != "after" {
		t.Fatalf("staged patched content: %q", got)
	}
}

func TestImportRollsBackWhenIndexIsLocked(t *testing.T) {
	src := repo(t)
	write(t, src, "item", "contents", 0644)
	commit(t, src, "source")
	work := repo(t)
	lock := filepath.Join(work, ".git", "index.lock")
	if err := os.WriteFile(lock, []byte("another writer"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: src, Dir: "nested", Depth: 1}); err == nil || !strings.Contains(err.Error(), "lock workspace index") {
		t.Fatalf("expected index lock error: %v", err)
	}
	if _, err := os.Stat(filepath.Join(work, "nested")); !os.IsNotExist(err) {
		t.Fatalf("failed import left files: %v", err)
	}
	if got, err := os.ReadFile(lock); err != nil || string(got) != "another writer" {
		t.Fatalf("another writer's lock changed: %q %v", got, err)
	}
	if got := git(t, work, "rev-parse", "--is-shallow-repository"); got != "false" {
		t.Fatalf("failed import changed shallow state: %q", got)
	}
}

func TestImportPreCheckoutPatchPreparesCaseCollisionsAndBlobs(t *testing.T) {
	src := repo(t)
	git(t, src, "commit", "--allow-empty", "-qm", "ancestor")
	ancestor := git(t, src, "rev-parse", "HEAD")
	// Build a tree with case-colliding directories entirely in the Git index;
	// this fixture also works on a case-insensitive filesystem.
	git(t, src, "-c", "core.ignorecase=false", "update-index", "--add", "--cacheinfo", "100644,"+hashBlob(t, src, "old upper\n")+",KORG/one")
	git(t, src, "-c", "core.ignorecase=false", "update-index", "--add", "--cacheinfo", "100644,"+hashBlob(t, src, "old lower\n")+",Korg/two")
	git(t, src, "commit", "-qm", "case-colliding source")
	base := git(t, src, "rev-parse", "HEAD")
	git(t, src, "-c", "core.ignorecase=false", "update-index", "--force-remove", "KORG/one")
	git(t, src, "-c", "core.ignorecase=false", "update-index", "--add", "--cacheinfo", "100644,"+hashBlob(t, src, "new upper\n")+",Korg/one")
	git(t, src, "-c", "core.ignorecase=false", "update-index", "--add", "--cacheinfo", "100644,"+hashBlob(t, src, "changed lower\n")+",Korg/two")
	git(t, src, "-c", "core.ignorecase=false", "update-index", "--add", "--cacheinfo", "100644,"+hashBlob(t, src, "brand new\n")+",Korg/new")
	cmd := exec.Command("git", "diff", "--cached", "--binary", "--full-index", base)
	cmd.Dir = src
	patch, err := cmd.Output()
	if err != nil {
		t.Fatal(err)
	}
	patchFile := filepath.Join(t.TempDir(), "prepare.patch")
	if err := os.WriteFile(patchFile, patch, 0644); err != nil {
		t.Fatal(err)
	}
	work := repo(t)
	got, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: fileURL(src), Commit: base, Depth: 2, PreCheckoutPatch: patchFile})
	if err != nil {
		t.Fatal(err)
	}
	if got != base || git(t, work, "cat-file", "-t", got) != "commit" {
		t.Fatalf("original parent not imported: %q", got)
	}
	if actual := git(t, work, "rev-parse", base+"^1"); actual != ancestor {
		t.Fatalf("original ancestry = %s, want %s", actual, ancestor)
	}
	for path, want := range map[string]string{"Korg/one": "new upper", "Korg/two": "changed lower", "Korg/new": "brand new"} {
		if got := git(t, work, "show", ":"+path); got != want {
			t.Fatalf("staged %s = %q, want %q", path, got, want)
		}
		if content, err := os.ReadFile(filepath.Join(work, path)); err != nil || strings.TrimSpace(string(content)) != want {
			t.Fatalf("installed %s = %q, %v", path, content, err)
		}
	}
	if paths := git(t, work, "ls-files", "KORG/one"); paths != "" {
		t.Fatalf("old case remains in index: %s", paths)
	}
	tree := git(t, work, "write-tree")
	composed := git(t, work, "commit-tree", tree, "-p", base, "-m", "composed")
	if parent := git(t, work, "rev-parse", composed+"^1"); parent != base {
		t.Fatalf("composed parent = %s, want %s", parent, base)
	}
}

func hashBlob(t *testing.T, dir, contents string) string {
	t.Helper()
	cmd := exec.Command("git", "hash-object", "-w", "--stdin")
	cmd.Dir = dir
	cmd.Stdin = strings.NewReader(contents)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("hash object: %v: %s", err, out)
	}
	return strings.TrimSpace(string(out))
}

func TestImportRejectsInvalidPreCheckoutPatchWithoutWorkspaceMutation(t *testing.T) {
	src := repo(t)
	write(t, src, "source.txt", "source\n", 0644)
	commit(t, src, "source")
	work := repo(t)
	write(t, work, "existing.txt", "keep\n", 0644)
	git(t, work, "add", "existing.txt")
	before := git(t, work, "write-tree")
	patchFile := filepath.Join(t.TempDir(), "invalid.patch")
	if err := os.WriteFile(patchFile, []byte("not a patch\n"), 0644); err != nil {
		t.Fatal(err)
	}
	_, err := composition.Import(context.Background(), work, composition.CloneRequest{URL: fileURL(src), Dir: "nested", Depth: 1, PreCheckoutPatch: patchFile})
	if err == nil || !strings.Contains(err.Error(), "pre-checkout patch") {
		t.Fatalf("expected pre-checkout patch error: %v", err)
	}
	if after := git(t, work, "write-tree"); after != before {
		t.Fatalf("workspace index changed: %s != %s", after, before)
	}
	if _, err := os.Stat(filepath.Join(work, "nested")); !os.IsNotExist(err) {
		t.Fatalf("failed import created destination: %v", err)
	}
	if shallow := git(t, work, "rev-parse", "--is-shallow-repository"); shallow != "false" {
		t.Fatalf("failed import changed shallow boundary: %s", shallow)
	}
}

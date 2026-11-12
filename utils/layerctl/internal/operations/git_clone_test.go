package operations_test

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/operations"
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
	got, err := operations.GitClone(ctx, work, operations.GitCloneRequest{URL: fileURL(src)})
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
	if _, err := operations.GitClone(ctx, work, operations.GitCloneRequest{URL: fileURL(other), Dir: "vendor/tool"}); err != nil {
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
	if _, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src)}); err == nil {
		t.Fatal("collision accepted")
	}
	if b, _ := os.ReadFile(filepath.Join(work, "same")); string(b) != "preserve" {
		t.Fatalf("overwrote content %q", b)
	}
	for _, dir := range []string{"../escape", "/absolute", "a/.git/x", "a/../x"} {
		if _, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src), Dir: dir}); err == nil {
			t.Fatalf("accepted %q", dir)
		}
	}
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(work, "link")); err != nil {
		t.Fatal(err)
	}
	if _, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src), Dir: "link/sub"}); err == nil {
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
	if got, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src), Dir: "old", Ref: branch, Commit: one}); err != nil || got != one {
		t.Fatalf("commit at ref: %s %v", got, err)
	}
	if _, err := operations.GitClone(context.Background(), repo(t), operations.GitCloneRequest{URL: fileURL(src), Ref: branch, Commit: one, Depth: 1}); err == nil || !strings.Contains(err.Error(), "shallow") {
		t.Fatalf("expected shallow unavailable: %v", err)
	}
	shallow := repo(t)
	if got, err := operations.GitClone(context.Background(), shallow, operations.GitCloneRequest{URL: fileURL(src), Dir: "first", Ref: branch, Depth: 2}); err != nil || got != tip {
		t.Fatalf("shallow import: %s %v", got, err)
	}
	if got := git(t, shallow, "rev-list", "--count", tip); got != "2" {
		t.Fatalf("shallow ancestry count %s", got)
	}
	if _, err := operations.GitClone(context.Background(), shallow, operations.GitCloneRequest{URL: fileURL(src), Dir: "second", Ref: branch, Commit: two}); err == nil || !strings.Contains(err.Error(), "overlapping") {
		t.Fatalf("expected overlapping shallow rejection: %v", err)
	}
	localShallow := repo(t)
	if got, err := operations.GitClone(context.Background(), localShallow, operations.GitCloneRequest{URL: src, Ref: branch, Depth: 1}); err != nil || got != tip {
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
	if _, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src)}); err == nil || !strings.Contains(err.Error(), "index") {
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
	if _, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: src, Dir: "copy"}); err == nil || !strings.Contains(err.Error(), "submodule") {
		t.Fatalf("submodule accepted: %v", err)
	}
	if _, err := os.Stat(filepath.Join(work, "copy")); !os.IsNotExist(err) {
		t.Fatalf("failed clone created files: %v", err)
	}
}

func TestImportDoesNotExposeSourceCredentialsInError(t *testing.T) {
	work := repo(t)
	secret := "unique-secret-for-test"
	_, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: "file://user:" + secret + "@invalid/repo"})
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
	if _, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: src, Commit: base}); err != nil {
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
	if _, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: src, Dir: "nested", Depth: 1}); err == nil || !strings.Contains(err.Error(), "lock workspace index") {
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
	got, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src), Commit: base, Depth: 2, PreCheckoutPatch: patchFile})
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
	_, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src), Dir: "nested", Depth: 1, PreCheckoutPatch: patchFile})
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

func hook(t *testing.T, script string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "hook.sh")
	if err := os.WriteFile(p, []byte("#!/bin/sh\nset -eu\n"+script+"\n"), 0755); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestImportPreCheckoutScriptRunsOnBarePreparedIndex(t *testing.T) {
	src := repo(t)
	write(t, src, "file", "before\n", 0644)
	base := commit(t, src, "base")
	write(t, src, "file", "patched\n", 0644)
	commit(t, src, "patch")
	cmd := exec.Command("git", "diff", "--binary", "--full-index", base, "HEAD")
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
	write(t, work, "workspace-marker", "already here", 0644)
	def := t.TempDir()
	script := hook(t, `
test "$(git rev-parse --is-bare-repository)" = true
test "$(pwd -P)" = "$(cd "$LAYERCTL_WORKTREE_DIR" && pwd -P)"
test -f workspace-marker
test ! -e file
test "$LAYERCTL_GITCLONE_BARE_DIR" = "$GIT_DIR"
test "$LAYERCTL_GITCLONE_INDEX_FILE" = "$GIT_INDEX_FILE"
test "$GIT_DIR" = "$LAYERCTL_GIT_DIR"
test "${GIT_WORK_TREE-unset}" = unset
test "$LAYERCTL_LAYER_ID" = layer-test
test "$LAYERCTL_OPERATION_INDEX" = 3
test -d "$LAYERCTL_DEFINITION_DIR"
test -d "$LAYERCTL_LAYER_DIR"
test -d "$LAYERCTL_WORKTREE_DIR"
test "$(git write-tree)" = "$LAYERCTL_SOURCE_TREE"
test "$(git show :file)" = patched
test "$(git show "$LAYERCTL_SOURCE_COMMIT:file")" = before
blob=$(printf 'from script\n' | git hash-object -w --stdin)
git update-index --add --cacheinfo "100644,$blob,new-file"
printf 'script diagnostic\n' >&2
git write-tree
`)
	layer := filepath.Dir(script)
	t.Setenv("GIT_WORK_TREE", filepath.Join(t.TempDir(), "wrong"))
	t.Setenv("GIT_INDEX_FILE", filepath.Join(t.TempDir(), "wrong-index"))
	got, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src), Commit: base, Depth: 1, PreCheckoutPatch: patchFile, PreCheckoutScript: script, DefinitionRoot: def, LayerDirectory: layer, LayerID: "layer-test", OperationIndex: 3})
	if err != nil {
		t.Fatal(err)
	}
	os.Unsetenv("GIT_WORK_TREE")
	os.Unsetenv("GIT_INDEX_FILE")
	if got != base || git(t, work, "show", ":file") != "patched" || git(t, work, "show", ":new-file") != "from script" {
		t.Fatal("script tree was not imported with the original parent")
	}
}

func TestImportPreCheckoutScriptReturnsCommit(t *testing.T) {
	src := repo(t)
	write(t, src, "file", "original\n", 0644)
	base := commit(t, src, "base")
	work := repo(t)
	t.Setenv("GIT_AUTHOR_NAME", "Hook author")
	t.Setenv("GIT_AUTHOR_EMAIL", "author@example.invalid")
	t.Setenv("GIT_COMMITTER_NAME", "Hook committer")
	t.Setenv("GIT_COMMITTER_EMAIL", "committer@example.invalid")
	t.Setenv("GIT_AUTHOR_DATE", "2001-02-03T04:05:06Z")
	t.Setenv("GIT_COMMITTER_DATE", "2002-03-04T05:06:07Z")
	script := hook(t, `
blob=$(printf 'rewritten\n' | git hash-object -w --stdin)
git update-index --add --cacheinfo "100644,$blob,file"
tree=$(git write-tree)
git commit-tree "$tree" -p "$LAYERCTL_SOURCE_COMMIT" -m generated
`)
	got, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src), Depth: 1, PreCheckoutScript: script})
	if err != nil {
		t.Fatal(err)
	}
	if got == base || git(t, work, "rev-parse", got+"^1") != base || git(t, work, "show", ":file") != "rewritten" {
		t.Fatal("script commit or its source parent was not imported")
	}
	if actual := git(t, work, "show", "-s", "--format=%an <%ae>|%cn <%ce>|%aI|%cI", got); actual != "Hook author <author@example.invalid>|Hook committer <committer@example.invalid>|2001-02-03T04:05:06Z|2002-03-04T05:06:07Z" {
		t.Fatalf("hook commit identity and dates = %q", actual)
	}
}

func TestImportRejectsInvalidPreCheckoutScriptOutput(t *testing.T) {
	src := repo(t)
	write(t, src, "source", "source\n", 0644)
	commit(t, src, "base")
	cases := map[string]string{
		"multiple lines": `echo "$LAYERCTL_SOURCE_COMMIT"; echo extra`,
		"short ID":       `printf 'abc\n'`,
		"unknown":        `printf '0000000000000000000000000000000000000000\n'`,
		"blob":           `printf x | git hash-object -w --stdin`,
		"tag": `export GIT_COMMITTER_NAME=Hook GIT_COMMITTER_EMAIL=hook@example.invalid
git tag -a example "$LAYERCTL_SOURCE_COMMIT" -m tag
git rev-parse refs/tags/example`,
		"nonzero":   `exit 1`,
		"oversized": `printf '%0100d\n' 0`,
	}
	for name, scriptText := range cases {
		t.Run(name, func(t *testing.T) {
			work := repo(t)
			write(t, work, "staged", "preserve", 0644)
			git(t, work, "add", "staged")
			before := git(t, work, "write-tree")
			_, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src), Dir: "nested", Depth: 1, PreCheckoutScript: hook(t, scriptText)})
			if err == nil {
				t.Fatal("invalid output accepted")
			}
			if git(t, work, "write-tree") != before || git(t, work, "rev-parse", "--is-shallow-repository") != "false" {
				t.Fatal("failed script mutated workspace index or shallow boundary")
			}
			if _, err := os.Stat(filepath.Join(work, "nested")); !os.IsNotExist(err) {
				t.Fatalf("failed script left destination: %v", err)
			}
		})
	}
}

func TestGitCloneRevalidatesHookAfterFetch(t *testing.T) {
	src := repo(t)
	write(t, src, "source", "source", 0644)
	commit(t, src, "base")
	work := repo(t)
	legitimate := hook(t, `printf '%s\n' "$LAYERCTL_SOURCE_COMMIT"`)
	attacker := hook(t, `touch "$SWAP_MARKER"; printf '%s\n' "$LAYERCTL_SOURCE_COMMIT"`)
	marker := filepath.Join(t.TempDir(), "ran")
	realGit, err := exec.LookPath("git")
	if err != nil {
		t.Fatal(err)
	}
	wrapperDir := t.TempDir()
	wrapper := `#!/bin/sh
"$REAL_GIT" "$@"
status=$?
case " $* " in
  *" fetch "*) rm -f "$SWAP_TARGET"; ln -s "$SWAP_ATTACKER" "$SWAP_TARGET" ;;
esac
exit "$status"
`
	if err := os.WriteFile(filepath.Join(wrapperDir, "git"), []byte(wrapper), 0755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", wrapperDir+string(os.PathListSeparator)+os.Getenv("PATH"))
	t.Setenv("REAL_GIT", realGit)
	t.Setenv("SWAP_TARGET", legitimate)
	t.Setenv("SWAP_ATTACKER", attacker)
	t.Setenv("SWAP_MARKER", marker)
	_, err = operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src), PreCheckoutScript: legitimate, LayerDirectory: filepath.Dir(legitimate)})
	if err == nil || !strings.Contains(err.Error(), "symlink") {
		t.Fatalf("expected swapped script to be rejected: %v", err)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("swapped script ran: %v", err)
	}
	if _, err := os.Stat(filepath.Join(work, "source")); !os.IsNotExist(err) {
		t.Fatalf("failed import changed workspace: %v", err)
	}
}

func TestGitCloneStagingRejectsCaseFoldedSymlinkParent(t *testing.T) {
	probe := t.TempDir()
	write(t, probe, "a", "probe", 0644)
	if _, err := os.Stat(filepath.Join(probe, "A")); os.IsNotExist(err) {
		t.Skip("filesystem is case-sensitive")
	} else if err != nil {
		t.Fatal(err)
	}
	src := repo(t)
	outside := t.TempDir()
	symlinkBlob := hashBlob(t, src, outside)
	dataBlob := hashBlob(t, src, "should stay inside staging\n")
	git(t, src, "-c", "core.ignorecase=false", "update-index", "--add", "--cacheinfo", "120000,"+symlinkBlob+",A")
	git(t, src, "-c", "core.ignorecase=false", "update-index", "--add", "--cacheinfo", "100644,"+dataBlob+",a/created")
	git(t, src, "commit", "-qm", "case-folded symlink parent")
	work := repo(t)
	_, err := operations.GitClone(context.Background(), work, operations.GitCloneRequest{URL: fileURL(src)})
	if err == nil {
		t.Fatal("accepted symlink parent on case-insensitive staging filesystem")
	}
	if _, err := os.Stat(filepath.Join(outside, "created")); !os.IsNotExist(err) {
		t.Fatalf("source tree escaped staging directory: %v", err)
	}
}

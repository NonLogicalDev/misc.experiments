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

func refreshCompositionFixture(t *testing.T) (string, string, *layer.Service, *projection.CompositionService) {
	t.Helper()
	for key, val := range map[string]string{"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"} {
		t.Setenv(key, val)
	}
	source := filepath.Join(t.TempDir(), "source")
	if err := os.Mkdir(source, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, source, "init", "-q")
	writeFile(t, filepath.Join(source, "file.txt"), "source\n", 0644)
	gitRun(t, source, "add", ".")
	gitRun(t, source, "commit", "-qm", "source")
	root := filepath.Join(t.TempDir(), "definitions")
	if err := os.Mkdir(root, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, root, "init", "-q")
	dir := filepath.Join(root, "layers", "0001-source")
	writeFile(t, filepath.Join(dir, "layer.toml"), fmt.Sprintf("[vcs]\ncommit-msg = \"Import\\n\"\n[[operation]]\n[operation.git-clone]\nurl = %q\ndir = \"\"\n[[operation]]\n[operation.overlay]\ndirectory = \"overlay\"\n", source), 0644)
	writeFile(t, filepath.Join(dir, "overlay", "script.sh"), "#!/bin/sh\n", 0755)
	if err := os.Symlink("script.sh", filepath.Join(dir, "overlay", "link")); err != nil {
		t.Fatal(err)
	}
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	git := &gitrepo.Repository{Root: root}
	composer := &projection.CompositionService{Definition: canonical, Git: git, Log: log.New(io.Discard, "", 0)}
	return root, source, &layer.Service{Definition: canonical, Git: git, Projection: composer}, composer
}

func TestRefreshCompositionPreservesCloneAndAncestry(t *testing.T) {
	root, source, service, composer := refreshCompositionFixture(t)
	originalSource := gitOutput(t, source, "rev-parse", "HEAD")
	worktree := filepath.Join(t.TempDir(), "workspace")
	made, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: worktree, Through: "0001-source"})
	if err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(worktree, "file.txt"), "edited\n", 0644)
	writeFile(t, filepath.Join(worktree, "extra.txt"), "new\n", 0644)
	gitRun(t, worktree, "add", "-A")
	gitRun(t, worktree, "commit", "-qm", "User edits")
	expectedTree := gitOutput(t, worktree, "rev-parse", "HEAD^{tree}")
	if err := service.RefreshComposition(t.Context(), "0001-source", "edit", composer); err != nil {
		t.Fatal(err)
	}
	layerDir := filepath.Join(root, "layers", "0001-source")
	got, err := definition.LoadUnit("0001-source", layerDir)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Operations) != 3 || got.Operations[0].Kind != "git-clone" || got.Operations[1].Kind != "overlay" || got.Operations[2].Kind != "patch" {
		t.Fatalf("operations = %#v", got.Operations)
	}
	if string(got.Message) != "User edits\n" {
		t.Fatalf("message = %q", got.Message)
	}
	if mode, err := os.Stat(filepath.Join(layerDir, "overlay", "script.sh")); err != nil || mode.Mode().Perm() != 0755 {
		t.Fatalf("overlay mode = %v, %v", mode, err)
	}
	if link, err := os.Readlink(filepath.Join(layerDir, "overlay", "link")); err != nil || link != "script.sh" {
		t.Fatalf("link = %q, %v", link, err)
	}
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	next, err := composer.Create(t.Context(), projection.CreateRequest{Name: "verify", Through: "0001-source"})
	if err != nil {
		t.Fatal(err)
	}
	defer composer.Delete(t.Context(), "verify")
	if gotTree := gitOutput(t, next.WorktreePath, "rev-parse", "HEAD^{tree}"); gotTree != expectedTree {
		t.Fatalf("tree = %s want %s", gotTree, expectedTree)
	}
	parents := strings.Fields(gitOutput(t, next.WorktreePath, "show", "-s", "--format=%P", "HEAD"))
	if len(parents) != 1 || parents[0] != originalSource {
		t.Fatalf("source ancestry = %v", parents)
	}
	if made.Base == next.Head {
		t.Fatal("expected changed layer")
	}
}

func TestRefreshCompositionRefusesChangedSourceWithoutChangingLayer(t *testing.T) {
	root, source, service, composer := refreshCompositionFixture(t)
	worktree := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: worktree, Through: "0001-source"}); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(worktree, "file.txt"), "edited\n", 0644)
	gitRun(t, worktree, "add", ".")
	gitRun(t, worktree, "commit", "-qm", "edit")
	manifestPath := filepath.Join(root, "layers", "0001-source", "layer.toml")
	before, err := os.ReadFile(manifestPath)
	if err != nil {
		t.Fatal(err)
	}
	// An upstream commit with the same tree still changes source ancestry.
	gitRun(t, source, "commit", "--allow-empty", "-qm", "moved ref")
	if err := service.RefreshComposition(t.Context(), "0001-source", "edit", composer); err == nil {
		t.Fatal("expected moved source rejection")
	}
	after, err := os.ReadFile(manifestPath)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatalf("manifest changed: %v", err)
	}
	entries, err := os.ReadDir(filepath.Join(root, "layers", "0001-source"))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 2 {
		t.Fatalf("unexpected entries: %v", entries)
	}
}

func TestRefreshCompositionRejectsDirtyWorkspace(t *testing.T) {
	root, _, service, composer := refreshCompositionFixture(t)
	worktree := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: worktree, Through: "0001-source"}); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(worktree, "file.txt"), "accepted\n", 0644)
	gitRun(t, worktree, "add", ".")
	gitRun(t, worktree, "commit", "-qm", "edit")
	writeFile(t, filepath.Join(worktree, "dirty.txt"), "keep me\n", 0644)
	manifest := filepath.Join(root, "layers", "0001-source", "layer.toml")
	before, err := os.ReadFile(manifest)
	if err != nil {
		t.Fatal(err)
	}
	if err := service.RefreshComposition(t.Context(), "0001-source", "edit", composer); err == nil || !strings.Contains(err.Error(), "uncommitted") {
		t.Fatalf("RefreshComposition() = %v", err)
	}
	after, err := os.ReadFile(manifest)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatalf("manifest changed: %v", err)
	}
	if got := readFile(t, filepath.Join(worktree, "dirty.txt")); got != "keep me\n" {
		t.Fatalf("uncommitted data changed: %q", got)
	}
}

func TestRefreshCompositionRejectsChangedManifest(t *testing.T) {
	root, _, service, composer := refreshCompositionFixture(t)
	worktree := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: worktree, Through: "0001-source"}); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(worktree, "file.txt"), "edited\n", 0644)
	gitRun(t, worktree, "add", ".")
	gitRun(t, worktree, "commit", "-qm", "edit")
	manifest := filepath.Join(root, "layers", "0001-source", "layer.toml")
	content, err := os.ReadFile(manifest)
	if err != nil {
		t.Fatal(err)
	}
	changed := append(content, []byte("\n# user's change\n")...)
	if err := os.WriteFile(manifest, changed, 0644); err != nil {
		t.Fatal(err)
	}
	// A comment changes bytes without changing the decoded layer: fingerprinting
	// protects against concurrent changes during refresh, but intentionally does
	// not treat comments as operation state. Do not discard a pre-existing comment.
	err = service.RefreshComposition(t.Context(), "0001-source", "edit", composer)
	if err == nil {
		t.Fatal("expected refusal rather than dropping the added comment")
	}
	after, err := os.ReadFile(manifest)
	if err != nil || !bytes.Equal(changed, after) {
		t.Fatalf("manifest changed: %v", err)
	}
}

func TestRefreshCompositionPreservesMultipleLayerAndSourceAncestry(t *testing.T) {
	root, _, _, composer := refreshCompositionFixture(t)
	child := filepath.Join(t.TempDir(), "child-source")
	if err := os.Mkdir(child, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, child, "init", "-q")
	writeFile(t, filepath.Join(child, "child.txt"), "child\n", 0644)
	gitRun(t, child, "add", ".")
	gitRun(t, child, "commit", "-qm", "child")
	childHead := gitOutput(t, child, "rev-parse", "HEAD")
	dir := filepath.Join(root, "layers", "0002-child")
	writeFile(t, filepath.Join(dir, "layer.toml"), fmt.Sprintf("[vcs]\ncommit-msg = \"Add child\\n\"\n[[operation]]\n[operation.git-clone]\nurl = %q\ndir = \"vendor/child\"\n", child), 0644)
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	service := &layer.Service{Definition: canonical, Git: &gitrepo.Repository{Root: root}, Projection: composer}
	worktree := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: worktree, Through: "0002-child"}); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(worktree, "file.txt"), "root changed\n", 0644)
	writeFile(t, filepath.Join(worktree, "vendor", "child", "child.txt"), "child changed\n", 0644)
	gitRun(t, worktree, "add", "-A")
	gitRun(t, worktree, "commit", "-qm", "Adjust composition")
	wantTree := gitOutput(t, worktree, "rev-parse", "HEAD^{tree}")
	if err := service.RefreshComposition(t.Context(), "0002-child", "edit", composer); err != nil {
		t.Fatal(err)
	}
	canonical, err = definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	verify, err := composer.Create(t.Context(), projection.CreateRequest{Name: "verify", Through: "0002-child"})
	if err != nil {
		t.Fatal(err)
	}
	defer composer.Delete(t.Context(), "verify")
	if got := gitOutput(t, verify.WorktreePath, "rev-parse", "HEAD^{tree}"); got != wantTree {
		t.Fatalf("tree = %s, want %s", got, wantTree)
	}
	parents := strings.Fields(gitOutput(t, verify.WorktreePath, "show", "-s", "--format=%P", "HEAD"))
	if len(parents) != 2 || parents[1] != childHead {
		t.Fatalf("source parents = %v", parents)
	}
}

func TestRefreshCompositionSkipsDisabledPredecessor(t *testing.T) {
	root, source, _, composer := refreshCompositionFixture(t)
	first := filepath.Join(root, "layers", "0001-source", "layer.toml")
	contents, err := os.ReadFile(first)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(first, append([]byte("[layer]\nenabled = false\n"), contents...), 0644); err != nil {
		t.Fatal(err)
	}
	second := filepath.Join(root, "layers", "0002-live")
	writeFile(t, filepath.Join(second, "layer.toml"), fmt.Sprintf("[vcs]\ncommit-msg = \"Live\\n\"\n[[operation]]\n[operation.git-clone]\nurl = %q\ndir = \"\"\n", source), 0644)
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	service := &layer.Service{Definition: canonical, Git: &gitrepo.Repository{Root: root}, Projection: composer}
	worktree := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit", WorktreePath: worktree, Through: "0002-live"}); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(worktree, "file.txt"), "edited\n", 0644)
	gitRun(t, worktree, "add", ".")
	gitRun(t, worktree, "commit", "-qm", "edit")
	if err := service.RefreshComposition(t.Context(), "0002-live", "edit", composer); err != nil {
		t.Fatal(err)
	}
}

func TestRefreshCompositionPreservesScriptAndSupportingFiles(t *testing.T) {
	for key, val := range map[string]string{"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid", "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"} {
		t.Setenv(key, val)
	}
	root := filepath.Join(t.TempDir(), "definitions")
	if err := os.Mkdir(root, 0755); err != nil {
		t.Fatal(err)
	}
	gitRun(t, root, "init", "-q")
	dir := filepath.Join(root, "layers", "0001-script")
	writeFile(t, filepath.Join(dir, "layer.toml"), `[vcs]
commit-msg = "Generate\n"
[[operation]]
[operation.script]
file = "scripts/run.sh"
args = ["world"]
`, 0644)
	writeFile(t, filepath.Join(dir, "scripts", "run.sh"), "#!/bin/sh\nprintf '%s %s\\n' \"$(cat \"$LAYERCTL_LAYER_DIR/config.txt\")\" \"$1\" > generated.txt\n", 0755)
	writeFile(t, filepath.Join(dir, "config.txt"), "hello\n", 0644)
	if err := os.Symlink("../config.txt", filepath.Join(dir, "scripts", "config-link")); err != nil {
		t.Fatal(err)
	}
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	git := &gitrepo.Repository{Root: root}
	composer := &projection.CompositionService{Definition: canonical, Git: git, Log: log.New(io.Discard, "", 0)}
	service := &layer.Service{Definition: canonical, Git: git, Projection: composer}
	worktree := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit-script", WorktreePath: worktree, Through: "0001-script"}); err != nil {
		t.Fatal(err)
	}
	if got := readFile(t, filepath.Join(worktree, "generated.txt")); got != "hello world\n" {
		t.Fatalf("generated = %q", got)
	}
	writeFile(t, filepath.Join(worktree, "generated.txt"), "edited\n", 0644)
	gitRun(t, worktree, "add", ".")
	gitRun(t, worktree, "commit", "-qm", "Edit generated")
	wantTree := gitOutput(t, worktree, "rev-parse", "HEAD^{tree}")
	if err := service.RefreshComposition(t.Context(), "0001-script", "edit-script", composer); err != nil {
		t.Fatal(err)
	}
	unit, err := definition.LoadUnit("0001-script", dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(unit.Operations) != 2 || unit.Operations[0].Kind != "script" || unit.Operations[1].Kind != "patch" || len(unit.Operations[0].Args) != 1 || unit.Operations[0].Args[0] != "world" {
		t.Fatalf("operations = %#v", unit.Operations)
	}
	if got := readFile(t, filepath.Join(dir, "config.txt")); got != "hello\n" {
		t.Fatalf("config = %q", got)
	}
	if got, err := os.Readlink(filepath.Join(dir, "scripts", "config-link")); err != nil || got != "../config.txt" {
		t.Fatalf("link = %q, %v", got, err)
	}
	canonical, err = definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	verified, err := composer.Create(t.Context(), projection.CreateRequest{Name: "verify-script", Through: "0001-script"})
	if err != nil {
		t.Fatal(err)
	}
	defer composer.Delete(t.Context(), "verify-script")
	if got := gitOutput(t, verified.WorktreePath, "rev-parse", "HEAD^{tree}"); got != wantTree {
		t.Fatalf("tree = %s; want %s", got, wantTree)
	}
}

func TestRefreshScriptLayerPreservesEarlierCloneAncestry(t *testing.T) {
	root, source, _, composer := refreshCompositionFixture(t)
	sourceCommit := gitOutput(t, source, "rev-parse", "HEAD")
	dir := filepath.Join(root, "layers", "0002-script")
	writeFile(t, filepath.Join(dir, "layer.toml"), `[layer]
depends-on = ["0001-source"]
[vcs]
commit-msg = "Run\n"
co-authors = ["Alice <alice@example.com>"]
[[operation]]
[operation.script]
file = "run.sh"
`, 0644)
	writeFile(t, filepath.Join(dir, "run.sh"), "#!/bin/sh\nprintf generated > extra.txt\n", 0755)
	canonical, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	git := &gitrepo.Repository{Root: root}
	service := &layer.Service{Definition: canonical, Git: git, Projection: composer}
	worktree := filepath.Join(t.TempDir(), "workspace")
	if _, err := composer.Create(t.Context(), projection.CreateRequest{Name: "edit-mixed", WorktreePath: worktree, Through: "0002-script"}); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(worktree, "extra.txt"), "edited\n", 0644)
	gitRun(t, worktree, "add", ".")
	gitRun(t, worktree, "commit", "-qm", "Modify")
	if err := service.RefreshComposition(t.Context(), "0002-script", "edit-mixed", composer); err != nil {
		t.Fatal(err)
	}
	unit, err := definition.LoadUnit("0002-script", dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(unit.DependsOn) != 1 || unit.DependsOn[0] != "0001-source" || len(unit.CoAuthors) != 1 || unit.CoAuthors[0] != "Alice <alice@example.com>" {
		t.Fatalf("metadata = %#v %#v", unit.DependsOn, unit.CoAuthors)
	}
	if string(unit.Message) != "Modify\n" {
		t.Fatalf("stored raw message = %q", unit.Message)
	}
	canonical, err = definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	composer.Definition = canonical
	verified, err := composer.Create(t.Context(), projection.CreateRequest{Name: "verify-mixed", Through: "0002-script"})
	if err != nil {
		t.Fatal(err)
	}
	defer composer.Delete(t.Context(), "verify-mixed")
	if got := gitOutput(t, verified.WorktreePath, "show", "-s", "--format=%P", "HEAD^"); got != sourceCommit {
		t.Fatalf("earlier source parent = %s; want %s", got, sourceCommit)
	}
	if got := gitOutput(t, verified.WorktreePath, "show", "-s", "--format=%B", "HEAD"); got != "Modify\n\nCo-authored-by: Alice <alice@example.com>" {
		t.Fatalf("formatted message = %q", got)
	}
}

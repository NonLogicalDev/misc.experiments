package definition_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

func TestManifestLoadsOperationsInOrderAndPreservesMessage(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "layer.toml"), `[vcs]
commit-msg = "First line\n\nBody\n\n"
[[operation]]
[operation.patch]
file = "changes.patch"
[[operation]]
[operation.overlay]
directory = "files"
`)
	writeFile(t, filepath.Join(dir, "changes.patch"), "patch data\n")
	writeFile(t, filepath.Join(dir, "files", "a.txt"), "added\n")
	unit, err := definition.LoadUnit("0001-feature", dir)
	if err != nil {
		t.Fatal(err)
	}
	if got := string(unit.Message); got != "First line\n\nBody\n\n" {
		t.Fatalf("message = %q", got)
	}
	if len(unit.Operations) != 2 || unit.Operations[0].Kind != "patch" || unit.Operations[1].Kind != "overlay" {
		t.Fatalf("operations = %#v", unit.Operations)
	}
	if got := unit.Operations[0].Path; got != filepath.Join(dir, "changes.patch") {
		t.Fatalf("patch path = %q", got)
	}
	if got := unit.Operations[1].Overlay; len(got) != 1 || got[0].Path != "a.txt" || string(got[0].Data) != "added\n" {
		t.Fatalf("overlay = %#v", got)
	}
}

func TestManifestRejectsUnsafeOrInvalidInputs(t *testing.T) {
	for _, tc := range []struct {
		name, manifest string
		setup          func(*testing.T, string)
	}{
		{"nul message", "[vcs]\ncommit-msg = \"hello\\u0000world\"\n", nil},
		{"invalid utf8 message", "[vcs]\ncommit-msg = \"hello\xff\"\n", nil},
		{"unreferenced file", "[vcs]\ncommit-msg = \"hello\"\n", func(t *testing.T, dir string) { writeFile(t, filepath.Join(dir, "notes.txt"), "ignored") }},
		{"missing message", "[vcs]\ncommit-msg = \"\"\n", nil},
		{"unknown key", "[vcs]\ncommit-msg = \"hello\"\nunexpected = true\n", nil},
		{"unknown operation", "[vcs]\ncommit-msg = \"hello\"\n[[operation]]\n[operation.exec]\nfile = \"f\"\n", nil},
		{"missing operation type", "[vcs]\ncommit-msg = \"hello\"\n[[operation]]\n", nil},
		{"multiple operation types", "[vcs]\ncommit-msg = \"hello\"\n[[operation]]\n[operation.patch]\nfile = \"f\"\n[operation.overlay]\ndirectory = \"o\"\n", nil},
		{"path escapes", "[vcs]\ncommit-msg = \"hello\"\n[[operation]]\n[operation.patch]\nfile = \"../f\"\n", nil},
		{"absolute path", "[vcs]\ncommit-msg = \"hello\"\n[[operation]]\n[operation.patch]\nfile = \"/tmp/f\"\n", nil},
		{"git metadata", "[vcs]\ncommit-msg = \"hello\"\n[[operation]]\n[operation.patch]\nfile = \".git/f\"\n", nil},
		{"symlink escape", "[vcs]\ncommit-msg = \"hello\"\n[[operation]]\n[operation.patch]\nfile = \"link/f\"\n", func(t *testing.T, dir string) {
			outside := t.TempDir()
			writeFile(t, filepath.Join(outside, "f"), "file")
			if err := os.Symlink(outside, filepath.Join(dir, "link")); err != nil {
				t.Fatal(err)
			}
		}},
		{"empty patch", "[vcs]\ncommit-msg = \"hello\"\n[[operation]]\n[operation.patch]\nfile = \"f\"\n", func(t *testing.T, dir string) { writeFile(t, filepath.Join(dir, "f"), "") }},
		{"unreferenced legacy patch", "[vcs]\ncommit-msg = \"hello\"\n", func(t *testing.T, dir string) { writeFile(t, filepath.Join(dir, "patch"), "old") }},
		{"mixed message files", "[vcs]\ncommit-msg = \"hello\"\n", func(t *testing.T, dir string) { writeFile(t, filepath.Join(dir, "COMMIT_EDITMSG"), "old") }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			writeFile(t, filepath.Join(dir, "layer.toml"), tc.manifest)
			if tc.setup != nil {
				tc.setup(t, dir)
			}
			if _, err := definition.LoadUnit("0001-feature", dir); err == nil {
				t.Fatal("expected invalid manifest to fail")
			}
		})
	}
}

func TestManifestAllowsMessageOnlyLayer(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "layer.toml"), "[vcs]\ncommit-msg = \"empty commit\\n\"\n")
	unit, err := definition.LoadUnit("0001-empty", dir)
	if err != nil || len(unit.Operations) != 0 {
		t.Fatalf("LoadUnit() = %#v, %v", unit, err)
	}
}

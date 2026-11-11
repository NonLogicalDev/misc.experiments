package definition_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

func TestClonePreCheckoutPatchInputs(t *testing.T) {
	for _, tc := range []struct {
		name, path string
		setup      func(*testing.T, string)
		wantOK     bool
	}{
		{"nested patch", "patches/rename.patch", func(t *testing.T, d string) { writeFile(t, filepath.Join(d, "patches/rename.patch"), "patch\n") }, true},
		{"empty name", "", nil, false},
		{"missing", "missing.patch", nil, false},
		{"empty file", "empty.patch", func(t *testing.T, d string) { writeFile(t, filepath.Join(d, "empty.patch"), "") }, false},
		{"directory", "patches", func(t *testing.T, d string) {
			if err := os.Mkdir(filepath.Join(d, "patches"), 0755); err != nil {
				t.Fatal(err)
			}
		}, false},
		{"parent traversal", "../outside.patch", nil, false},
		{"absolute", "/tmp/outside.patch", nil, false},
		{"git metadata", ".git/config", nil, false},
		{"manifest itself", "layer.toml", nil, false},
		{"backslash", `patches\rename.patch`, nil, false},
		{"file symlink", "link.patch", func(t *testing.T, d string) {
			target := filepath.Join(t.TempDir(), "target")
			writeFile(t, target, "x")
			if err := os.Symlink(target, filepath.Join(d, "link.patch")); err != nil {
				t.Fatal(err)
			}
		}, false},
		{"parent symlink", "link/target", func(t *testing.T, d string) {
			target := t.TempDir()
			writeFile(t, filepath.Join(target, "target"), "x")
			if err := os.Symlink(target, filepath.Join(d, "link")); err != nil {
				t.Fatal(err)
			}
		}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			writeFile(t, filepath.Join(dir, "layer.toml"), "[vcs]\ncommit-msg = 'message'\n[[operation]]\n[operation.git-clone]\nurl = 'repo'\ndir = ''\npre-checkout-patch = '"+tc.path+"'\n")
			if tc.setup != nil {
				tc.setup(t, dir)
			}
			unit, err := definition.LoadUnit("0001-test", dir)
			if (err == nil) != tc.wantOK {
				t.Fatalf("LoadUnit error = %v, want success %v", err, tc.wantOK)
			}
			if tc.wantOK && unit.Operations[0].PreCheckoutPatch != filepath.Join(dir, tc.path) {
				t.Fatalf("patch path = %q", unit.Operations[0].PreCheckoutPatch)
			}
		})
	}
}

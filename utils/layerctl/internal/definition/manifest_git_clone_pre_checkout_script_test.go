package definition_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

func TestClonePreCheckoutScriptInputs(t *testing.T) {
	executable := func(t *testing.T, path string) {
		t.Helper()
		writeFile(t, path, "#!/bin/sh\nexit 0\n")
		if err := os.Chmod(path, 0755); err != nil {
			t.Fatal(err)
		}
	}
	for _, tc := range []struct {
		name, path string
		setup      func(*testing.T, string)
		ok         bool
	}{
		{"nested executable with support assets", "scripts/prepare", func(t *testing.T, d string) {
			executable(t, filepath.Join(d, "scripts", "prepare"))
			writeFile(t, filepath.Join(d, "config.txt"), "support")
		}, true},
		{"empty path", "", nil, false},
		{"missing", "missing", nil, false},
		{"empty script", "empty", func(t *testing.T, d string) {
			writeFile(t, filepath.Join(d, "empty"), "")
			if err := os.Chmod(filepath.Join(d, "empty"), 0755); err != nil {
				t.Fatal(err)
			}
		}, false},
		{"not executable", "run", func(t *testing.T, d string) { writeFile(t, filepath.Join(d, "run"), "#!/bin/sh\n") }, false},
		{"directory", "scripts", func(t *testing.T, d string) {
			if err := os.Mkdir(filepath.Join(d, "scripts"), 0755); err != nil {
				t.Fatal(err)
			}
		}, false},
		{"parent", "../outside", nil, false},
		{"absolute", "/tmp/outside", nil, false},
		{"git metadata", ".git/config", nil, false},
		{"manifest", "layer.toml", nil, false},
		{"backslash", `scripts\prepare`, nil, false},
		{"symlink", "link", func(t *testing.T, d string) {
			target := filepath.Join(t.TempDir(), "target")
			executable(t, target)
			if err := os.Symlink(target, filepath.Join(d, "link")); err != nil {
				t.Fatal(err)
			}
		}, false},
		{"symlink parent", "link/target", func(t *testing.T, d string) {
			target := t.TempDir()
			executable(t, filepath.Join(target, "target"))
			if err := os.Symlink(target, filepath.Join(d, "link")); err != nil {
				t.Fatal(err)
			}
		}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			writeFile(t, filepath.Join(dir, "layer.toml"), "[vcs]\ncommit-msg = 'message'\n[[operation]]\n[operation.git-clone]\nurl = 'repo'\npre-checkout-script = '"+tc.path+"'\n")
			if tc.setup != nil {
				tc.setup(t, dir)
			}
			unit, err := definition.LoadUnit("0001-test", dir)
			if (err == nil) != tc.ok {
				t.Fatalf("LoadUnit error = %v, want success %v", err, tc.ok)
			}
			if tc.ok && (unit.Operations[0].PreCheckoutScript != filepath.Join(dir, tc.path) || unit.Operations[0].Dir != "") {
				t.Fatalf("operation = %#v", unit.Operations[0])
			}
		})
	}
}

func TestCloneDirDefaultsToRoot(t *testing.T) {
	for _, item := range []struct {
		name, field, want string
		valid             bool
	}{
		{"omitted", "", "", true},
		{"empty", "dir = ''\n", "", true},
		{"nested", "dir = 'a/b'\n", "a/b", true},
		{"invalid type", "dir = 1\n", "", false},
		{"traversal", "dir = '../outside'\n", "", false},
	} {
		t.Run(item.name, func(t *testing.T) {
			d := t.TempDir()
			writeFile(t, filepath.Join(d, "layer.toml"), "[vcs]\ncommit-msg='test'\n[[operation]]\n[operation.git-clone]\nurl='repo'\n"+item.field)
			u, err := definition.LoadUnit("0001-test", d)
			if (err == nil) != item.valid {
				t.Fatalf("error = %v", err)
			}
			if item.valid && u.Operations[0].Dir != item.want {
				t.Fatalf("dir = %q, want %q", u.Operations[0].Dir, item.want)
			}
		})
	}
}

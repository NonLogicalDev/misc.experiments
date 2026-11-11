package definition_test

import (
	"net"
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

func TestManifestLoadsGitCloneWithRootAndNestedDestinations(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "layer.toml"), `[vcs]
commit-msg = "Compose\n"
[[operation]]
[operation.git-clone]
url = "https://example.invalid/primary.git"
dir = ""
ref = "stable"
commit = "abcdef12"
depth = 5
[[operation]]
[operation.git-clone]
url = "/local/other.git"
dir = "vendor/other"
`)
	unit, err := definition.LoadUnit("0001-compose", dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(unit.Operations) != 2 {
		t.Fatalf("operations = %#v", unit.Operations)
	}
	first, second := unit.Operations[0], unit.Operations[1]
	if first.Kind != "git-clone" || first.URL != "https://example.invalid/primary.git" || first.Dir != "" || first.Ref != "stable" || first.Commit != "abcdef12" || first.Depth != 5 {
		t.Fatalf("root clone = %#v", first)
	}
	if second.Kind != "git-clone" || second.URL != "/local/other.git" || second.Dir != "vendor/other" || second.Ref != "" || second.Commit != "" || second.Depth != 0 {
		t.Fatalf("nested clone = %#v", second)
	}
}

func TestManifestRejectsInvalidGitClone(t *testing.T) {
	for _, tc := range []struct{ name, clone string }{
		{"missing URL", `dir = ""`},
		{"empty URL", "url = \"\"\ndir = \"\""},
		{"missing dir", `url = "repo"`},
		{"zero depth", "url = \"repo\"\ndir = \"\"\ndepth = 0"},
		{"negative depth", "url = \"repo\"\ndir = \"\"\ndepth = -1"},
		{"string depth", "url = \"repo\"\ndir = \"\"\ndepth = \"2\""},
		{"option ref", "url = \"repo\"\ndir = \"\"\nref = \"--evil\""},
		{"option commit", "url = \"repo\"\ndir = \"\"\ncommit = \"--evil\""},
		{"NUL commit", `url = "repo"
dir = ""
commit = "a\u0000b"`},
		{"obsolete rev", "url = \"repo\"\ndir = \"\"\nrev = \"old\""},
		{"obsolete branch", "url = \"repo\"\ndir = \"\"\nbranch = \"old\""},
		{"parent", "url = \"repo\"\ndir = \"../outside\""},
		{"absolute", "url = \"repo\"\ndir = \"/outside\""},
		{"dot", "url = \"repo\"\ndir = \".\""},
		{"git metadata", "url = \"repo\"\ndir = \"nested/.GIT/files\""},
		{"windows path", "url = \"repo\"\ndir = \"C:/outside\""},
		{"backslash", `url = "repo"
dir = 'one\two'`},
		{"NUL", `url = "repo"
dir = "a\u0000b"`},
		{"unknown key", "url = \"repo\"\ndir = \"\"\nunknown = \"x\""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			writeFile(t, filepath.Join(dir, "layer.toml"), "[vcs]\ncommit-msg = \"Message\\n\"\n[[operation]]\n[operation.git-clone]\n"+tc.clone+"\n")
			if _, err := definition.LoadUnit("0001-clone", dir); err == nil {
				t.Fatal("expected invalid clone to fail")
			}
		})
	}
}

func TestManifestRejectsGitCloneWithAnotherOperationType(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "layer.toml"), `[vcs]
commit-msg = "Message\n"
[[operation]]
[operation.git-clone]
url = "repo"
dir = ""
[operation.patch]
file = "patch"
`)
	writeFile(t, filepath.Join(dir, "patch"), "patch")
	if _, err := definition.LoadUnit("0001-invalid", dir); err == nil {
		t.Fatal("expected mixed operation types to fail")
	}
}

func TestCompositionLayerEnablementAndDependencies(t *testing.T) {
	for _, tc := range []struct {
		name, first, second string
		valid               bool
	}{
		{"enabled default and earlier dependency", "[vcs]\ncommit-msg = \"first\"\n", "[layer]\ndepends-on = [\"0001-base\"]\n[vcs]\ncommit-msg = \"second\"\n", true},
		{"disabled unreferenced layer", "[layer]\nenabled = false\n[vcs]\ncommit-msg = \"first\"\n", "[vcs]\ncommit-msg = \"second\"\n", true},
		{"enabled depends on disabled", "[layer]\nenabled = false\n[vcs]\ncommit-msg = \"first\"\n", "[layer]\ndepends-on = [\"0001-base\"]\n[vcs]\ncommit-msg = \"second\"\n", false},
		{"missing dependency", "[vcs]\ncommit-msg = \"first\"\n", "[layer]\ndepends-on = [\"0000-missing\"]\n[vcs]\ncommit-msg = \"second\"\n", false},
		{"forward dependency", "[layer]\ndepends-on = [\"0002-next\"]\n[vcs]\ncommit-msg = \"first\"\n", "[vcs]\ncommit-msg = \"second\"\n", false},
		{"repeated dependency", "[vcs]\ncommit-msg = \"first\"\n", "[layer]\ndepends-on = [\"0001-base\", \"0001-base\"]\n[vcs]\ncommit-msg = \"second\"\n", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := t.TempDir()
			writeFile(t, filepath.Join(root, "layers", "0001-base", "layer.toml"), tc.first)
			writeFile(t, filepath.Join(root, "layers", "0002-next", "layer.toml"), tc.second)
			repo, err := definition.Load(root)
			if (err == nil) != tc.valid {
				t.Fatalf("Load() = %v, want valid %v", err, tc.valid)
			}
			if tc.valid && tc.name == "disabled unreferenced layer" && !repo.Layers[0].Disabled {
				t.Fatal("disabled layer was not retained")
			}
		})
	}
}

func TestManifestLoadsExecutableScriptAndArguments(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "scripts", "run.sh")
	writeFile(t, script, "#!/bin/sh\nexit 0\n")
	if err := os.Chmod(script, 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "layer.toml"), `[vcs]
commit-msg = "Script\n"
[[operation]]
[operation.script]
file = "scripts/run.sh"
args = ["hello world", "--option", ""]
`)
	unit, err := definition.LoadUnit("0001-script", dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(unit.Operations) != 1 || unit.Operations[0].Kind != "script" || unit.Operations[0].Path != script || len(unit.Operations[0].Args) != 3 || unit.Operations[0].Args[0] != "hello world" || unit.Operations[0].Args[2] != "" {
		t.Fatalf("operations = %#v", unit.Operations)
	}
}

func TestManifestRejectsInvalidScripts(t *testing.T) {
	cases := []struct {
		name, file string
		setup      func(*testing.T, string)
	}{
		{"missing", "missing.sh", nil},
		{"not executable", "run.sh", func(t *testing.T, d string) { writeFile(t, filepath.Join(d, "run.sh"), "#!/bin/sh\n") }},
		{"escaping", "../run.sh", nil},
		{"symlink", "run.sh", func(t *testing.T, d string) {
			p := filepath.Join(t.TempDir(), "outside")
			writeFile(t, p, "#!/bin/sh\n")
			if err := os.Symlink(p, filepath.Join(d, "run.sh")); err != nil {
				t.Fatal(err)
			}
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			if tc.setup != nil {
				tc.setup(t, dir)
			}
			writeFile(t, filepath.Join(dir, "layer.toml"), "[vcs]\ncommit-msg = \"Script\\n\"\n[[operation]]\n[operation.script]\nfile = \""+tc.file+"\"\n")
			if _, err := definition.LoadUnit("0001-script", dir); err == nil {
				t.Fatal("expected invalid script rejection")
			}
		})
	}
}

func TestManifestRejectsInvalidScriptArgumentsAndFields(t *testing.T) {
	cases := []string{`args = ["bad\u0000arg"]`, `args = "not an array"`, `unexpected = "field"`}
	for _, extra := range cases {
		t.Run(extra, func(t *testing.T) {
			dir := t.TempDir()
			p := filepath.Join(dir, "run.sh")
			writeFile(t, p, "#!/bin/sh\n")
			if err := os.Chmod(p, 0755); err != nil {
				t.Fatal(err)
			}
			writeFile(t, filepath.Join(dir, "layer.toml"), "[vcs]\ncommit-msg = \"Run\\n\"\n[[operation]]\n[operation.script]\nfile = \"run.sh\"\n"+extra+"\n")
			if _, err := definition.LoadUnit("0001-script", dir); err == nil {
				t.Fatal("expected invalid script metadata rejection")
			}
		})
	}
}

func TestManifestCoAuthors(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "layer.toml"), `[vcs]
commit-msg = "Message\n"
co-authors = ["Alice <alice@example.com>", "Bob Smith <bob@example.com>"]
`)
	unit, err := definition.LoadUnit("0001-test", dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(unit.CoAuthors) != 2 || unit.CoAuthors[0] != "Alice <alice@example.com>" || unit.CoAuthors[1] != "Bob Smith <bob@example.com>" {
		t.Fatalf("authors = %#v", unit.CoAuthors)
	}
}
func TestManifestRejectsInvalidCoAuthors(t *testing.T) {
	for _, value := range []string{`["Alice <a@example.com>\nInjected"]`, `["<a@example.com>"]`, `["Alice <a@example.com> <b@example.com>"]`, `["Alice <a b@example.com>"]`, `"Alice <a@example.com>"`} {
		t.Run(value, func(t *testing.T) {
			dir := t.TempDir()
			writeFile(t, filepath.Join(dir, "layer.toml"), "[vcs]\ncommit-msg = \"Message\\n\"\nco-authors = "+value+"\n")
			if _, err := definition.LoadUnit("0001-test", dir); err == nil {
				t.Fatal("accepted invalid author")
			}
		})
	}
}

func TestScriptLayerAllowsSupportingFilesAndSymlinks(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "scripts", "run.sh")
	writeFile(t, script, "#!/bin/sh\nexit 0\n")
	if err := os.Chmod(script, 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "config", "settings.toml"), "value = 1\n")
	writeFile(t, filepath.Join(dir, "helpers", "library.sh"), "helper\n")
	if err := os.Symlink("../config/settings.toml", filepath.Join(dir, "helpers", "config-link")); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "layer.toml"), `[vcs]
commit-msg = "Run\n"
[[operation]]
[operation.script]
file = "scripts/run.sh"
`)
	unit, err := definition.LoadUnit("0001-script", dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(unit.Operations) != 1 || unit.Operations[0].Kind != "script" {
		t.Fatalf("operations = %#v", unit.Operations)
	}
}

func TestScriptLayerRejectsSpecialSupportingFile(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "run.sh")
	writeFile(t, script, "#!/bin/sh\nexit 0\n")
	if err := os.Chmod(script, 0755); err != nil {
		t.Fatal(err)
	}
	writeFile(t, filepath.Join(dir, "layer.toml"), "[vcs]\ncommit-msg = \"Run\\n\"\n[[operation]]\n[operation.script]\nfile = \"run.sh\"\n")
	sock, err := net.Listen("unix", filepath.Join(dir, "socket"))
	if err != nil {
		t.Skipf("Unix socket unavailable: %v", err)
	}
	defer sock.Close()
	if _, err := definition.LoadUnit("0001-script", dir); err == nil {
		t.Fatal("expected special supporting file rejection")
	}
}

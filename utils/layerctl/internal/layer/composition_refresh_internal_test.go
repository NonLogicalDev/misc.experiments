package layer

import (
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestRefreshDetectsCommentsWithoutMisreadingQuotedHashes(t *testing.T) {
	for _, tc := range []struct {
		name, text string
		want       bool
	}{
		{"plain comment", "[vcs]\n# a note\ncommit-msg = \"hi\"\n", true},
		{"trailing comment", "commit-msg = \"hi\" # a note\n", true},
		{"hash in basic", "commit-msg = \"# inside\"\n", false},
		{"hash after escaped quote", "commit-msg = \"a\\\"#inside\"\n", false},
		{"hash in literal", "commit-msg = '# inside'\n", false},
		{"hash in multiline basic", "commit-msg = \"\"\"\n# inside\ntext\n\"\"\"\n", false},
		{"hash in multiline literal", "commit-msg = '''\n# inside\ntext\n'''\n", false},
		{"comment after multiline", "commit-msg = \"\"\"\n# inside\n\"\"\" # outside\n", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := refreshHasTOMLComment([]byte(tc.text)); got != tc.want {
				t.Fatalf("comment detection = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestRefreshWriteManifestRetainsLayerMetadata(t *testing.T) {
	dir := t.TempDir()
	unit := definition.Unit{ID: "0003-later", Directory: dir, Disabled: true, DependsOn: []string{"0001-first", "0002-second"}}
	if err := refreshWriteManifest(dir, unit, []byte("message\n"), ""); err != nil {
		t.Fatal(err)
	}
	got, err := definition.LoadUnit(unit.ID, dir)
	if err != nil {
		t.Fatal(err)
	}
	if !got.Disabled || !slices.Equal(got.DependsOn, unit.DependsOn) {
		t.Fatalf("metadata = disabled %v, dependencies %v", got.Disabled, got.DependsOn)
	}
}

func TestRefreshWriteManifestRetainsScriptAndArguments(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "script.sh")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nexit 0\n"), 0755); err != nil {
		t.Fatal(err)
	}
	args := []string{"one space", "--flag", ""}
	unit := definition.Unit{ID: "0001-script", Directory: dir, Operations: []definition.Operation{{Kind: "script", Path: script, Args: args}}}
	if err := refreshWriteManifest(dir, unit, []byte("message\n"), ""); err != nil {
		t.Fatal(err)
	}
	got, err := definition.LoadUnit(unit.ID, dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Operations) != 1 || got.Operations[0].Kind != "script" || got.Operations[0].Path != script || !slices.Equal(got.Operations[0].Args, args) {
		t.Fatalf("script = %#v", got.Operations)
	}
}

func TestRefreshWriteManifestRetainsCoAuthors(t *testing.T) {
	dir := t.TempDir()
	unit := definition.Unit{ID: "0001-test", Directory: dir, CoAuthors: []string{"Alice <alice@example.com>", "Bob <bob@example.com>"}}
	if err := refreshWriteManifest(dir, unit, []byte("message\n"), ""); err != nil {
		t.Fatal(err)
	}
	got, err := definition.LoadUnit(unit.ID, dir)
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(got.CoAuthors, unit.CoAuthors) {
		t.Fatalf("coauthors = %#v", got.CoAuthors)
	}
}

func TestRefreshWriteManifestRetainsPreCheckoutPatch(t *testing.T) {
	dir := t.TempDir()
	input := filepath.Join(dir, "patches", "rename.patch")
	if err := os.MkdirAll(filepath.Dir(input), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(input, []byte("patch\n"), 0644); err != nil {
		t.Fatal(err)
	}
	unit := definition.Unit{ID: "0001-test", Directory: dir, Operations: []definition.Operation{{Kind: "git-clone", URL: "repo", PreCheckoutPatch: input}}}
	if err := refreshWriteManifest(dir, unit, []byte("message\n"), ""); err != nil {
		t.Fatal(err)
	}
	got, err := definition.LoadUnit(unit.ID, dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Operations) != 1 || got.Operations[0].PreCheckoutPatch != input {
		t.Fatalf("operations = %#v", got.Operations)
	}
}

func TestRefreshWriteManifestRetainsPreCheckoutScriptAndSupport(t *testing.T) {
	dir := t.TempDir()
	script := filepath.Join(dir, "scripts", "prepare")
	if err := os.MkdirAll(filepath.Dir(script), 0755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(script, []byte("#!/bin/sh\nexit 0\n"), 0755); err != nil {
		t.Fatal(err)
	}
	support := filepath.Join(dir, "config.txt")
	if err := os.WriteFile(support, []byte("support"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../config.txt", filepath.Join(dir, "scripts", "config-link")); err != nil {
		t.Fatal(err)
	}
	unit := definition.Unit{ID: "0001-test", Directory: dir, Operations: []definition.Operation{{Kind: "git-clone", URL: "repo", PreCheckoutScript: script}}}
	candidate := t.TempDir()
	if err := refreshCopyDirectory(dir, candidate); err != nil {
		t.Fatal(err)
	}
	if err := refreshWriteManifest(candidate, unit, []byte("message\n"), ""); err != nil {
		t.Fatal(err)
	}
	got, err := definition.LoadUnit(unit.ID, candidate)
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Operations) != 1 || got.Operations[0].PreCheckoutScript != filepath.Join(candidate, "scripts", "prepare") {
		t.Fatalf("operations = %#v", got.Operations)
	}
	if data, err := os.ReadFile(filepath.Join(candidate, "config.txt")); err != nil || string(data) != "support" {
		t.Fatalf("support = %q, %v", data, err)
	}
	if target, err := os.Readlink(filepath.Join(candidate, "scripts", "config-link")); err != nil || target != "../config.txt" {
		t.Fatalf("support link = %q, %v", target, err)
	}
}

func TestRefreshWriteManifestCloneDirDefaultsToRoot(t *testing.T) {
	for _, tc := range []struct {
		name, dir string
		wantDir   bool
	}{{"root", "", false}, {"nested", "vendor/project", true}} {
		t.Run(tc.name, func(t *testing.T) {
			d := t.TempDir()
			u := definition.Unit{ID: "0001-test", Directory: d, Operations: []definition.Operation{{Kind: "git-clone", URL: "repo", Dir: tc.dir}}}
			if err := refreshWriteManifest(d, u, []byte("message\n"), ""); err != nil {
				t.Fatal(err)
			}
			raw, err := os.ReadFile(filepath.Join(d, "layer.toml"))
			if err != nil {
				t.Fatal(err)
			}
			if strings.Contains(string(raw), "\ndir = ") != tc.wantDir {
				t.Fatalf("dir serialization: %s", raw)
			}
			got, err := definition.LoadUnit(u.ID, d)
			if err != nil {
				t.Fatal(err)
			}
			if got.Operations[0].Dir != tc.dir {
				t.Fatalf("dir = %q", got.Operations[0].Dir)
			}
		})
	}
}

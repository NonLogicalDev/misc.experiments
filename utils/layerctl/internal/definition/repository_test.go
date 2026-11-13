// Modified from abg-OAI/codex: module import path changed for this extraction.
package definition_test

import (
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

func TestLoadSortsNumberedLayerDirectories(t *testing.T) {
	root := t.TempDir()

	writeLayer(t, root, "0000-foundation", true)
	writeLayer(t, root, "0002-second", false)
	writeLayer(t, root, "0001-first", true)

	repository, err := definition.Load(root)
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}

	gotLayers := []string{repository.Layers[0].ID, repository.Layers[1].ID, repository.Layers[2].ID}
	if want := []string{"0000-foundation", "0001-first", "0002-second"}; !reflect.DeepEqual(gotLayers, want) {
		t.Fatalf("layer order = %v, want %v", gotLayers, want)
	}
	if got, want := filepath.Base(repository.Layers[2].Directory), "0002-second"; got != want {
		t.Fatalf("last directory = %q, want %q", got, want)
	}
	if len(repository.Layers[1].Operations) == 0 {
		t.Fatal("first product layer has no patch")
	}
	if len(repository.Layers[2].Operations) != 0 {
		t.Fatalf("second product layer operations = %v, want none", repository.Layers[2].Operations)
	}
}

func TestLoadRejectsUnnumberedLayer(t *testing.T) {
	root := t.TempDir()

	writeLayer(t, root, "0000-foundation", true)
	writeLayer(t, root, "feature", true)

	if _, err := definition.Load(root); err == nil {
		t.Fatal("Load() error = nil, want invalid layer directory error")
	}
}

func TestLoadRejectsMailPatchLayer(t *testing.T) {
	root := t.TempDir()

	writeFile(t, filepath.Join(root, "layers", "0000-foundation.patch"), "foundation\n")

	if _, err := definition.Load(root); err == nil {
		t.Fatal("Load() error = nil, want mail patch layer error")
	}
}

func TestLoadRejectsMalformedLayerContents(t *testing.T) {
	for _, test := range []struct {
		name  string
		setup func(*testing.T, string)
	}{
		{
			name: "missing message",
			setup: func(t *testing.T, root string) {
				writeFile(t, filepath.Join(root, "layers", "0000-foundation", "patch"), "patch\n")
			},
		},
		{
			name: "empty message",
			setup: func(t *testing.T, root string) {
				writeFile(t, filepath.Join(root, "layers", "0000-foundation", "COMMIT_EDITMSG"), "")
			},
		},
		{
			name: "empty patch",
			setup: func(t *testing.T, root string) {
				writeLayer(t, root, "0000-foundation", false)
				writeFile(t, filepath.Join(root, "layers", "0000-foundation", "patch"), "")
			},
		},
		{
			name: "unknown entry",
			setup: func(t *testing.T, root string) {
				writeLayer(t, root, "0000-foundation", false)
				writeFile(t, filepath.Join(root, "layers", "0000-foundation", "extra"), "extra\n")
			},
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			root := t.TempDir()

			test.setup(t, root)
			if _, err := definition.Load(root); err == nil {
				t.Fatal("Load() error = nil, want malformed layer error")
			}
		})
	}
}

func TestLoadAllowsRepositoryWithoutProductLayers(t *testing.T) {
	root := t.TempDir()

	writeLayer(t, root, "0000-foundation", false)

	repository, err := definition.Load(root)
	if err != nil {
		t.Fatalf("Load() error = %v", err)
	}
	if got, want := len(repository.Layers), 1; got != want {
		t.Fatalf("len(Load().Layers) = %d, want %d", got, want)
	}
}

func writeLayer(t *testing.T, root, id string, withPatch bool) {
	t.Helper()
	directory := filepath.Join(root, "layers", id)
	manifest := "[vcs]\ncommit-msg = " + strconv.Quote(id+"\n") + "\n"
	if withPatch {
		manifest += "[[operation]]\n[operation.patch]\nfile = 'patch'\n"
	}
	writeFile(t, filepath.Join(directory, "layer.toml"), manifest)
	if withPatch {
		writeFile(t, filepath.Join(directory, "patch"), "patch\n")
	}
}

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("MkdirAll(%q) error = %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("WriteFile(%q) error = %v", path, err)
	}
}

func TestLoadCompositionWithoutUpstreamUsesNumberedOrder(t *testing.T) {
	root := t.TempDir()
	writeLayer(t, root, "0008-second", false)
	writeLayer(t, root, "0001-first", false)
	repo, err := definition.Load(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(repo.Layers) != 2 || repo.Layers[0].ID != "0001-first" || repo.Layers[1].ID != "0008-second" {
		t.Fatalf("layer order = %#v", repo.Layers)
	}
}

func TestLoadCompositionRequiresAtLeastOneLayer(t *testing.T) {
	if _, err := definition.Load(t.TempDir()); err == nil {
		t.Fatal("expected empty composition to fail")
	}
}

func TestLoadRejectsLegacyLayer(t *testing.T) {
	root := t.TempDir()
	writeFile(t, filepath.Join(root, "layers", "0001-old", "COMMIT_EDITMSG"), "old\n")
	if _, err := definition.Load(root); err == nil || !strings.Contains(err.Error(), "layer.toml") {
		t.Fatalf("expected missing manifest error, got %v", err)
	}
}

func TestLoadRejectsOldUpstreamEvenWithManifests(t *testing.T) {
	root := t.TempDir()
	writeLayer(t, root, "0001-base", false)
	writeFile(t, filepath.Join(root, "upstream.json"), "{}")
	if _, err := definition.Load(root); err == nil || !strings.Contains(err.Error(), "no longer supported") {
		t.Fatalf("expected unsupported upstream error, got %v", err)
	}
}

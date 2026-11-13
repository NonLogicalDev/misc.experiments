// Modified from abg-OAI/codex: manifest-based layer definitions added.
// Package definition reads and validates a layer definition repository.
// It owns the on-disk layer representation, while projection and maintenance
// packages own operations performed with those definitions.
package definition

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
)

var layerIDPattern = regexp.MustCompile(`^[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*$`)

// Repository is one complete layer definition.
// Layers are ordered lexically by their numbered directory names.
type Repository struct {
	Root   string
	Layers []Unit
}

// Operation describes one validated manifest operation, in declared order.
// Path is an absolute path to its patch file or overlay directory.
type Operation struct {
	Kind    string
	Path    string
	Overlay []OverlayEntry
	URL     string
	Dir     string
	Ref     string
	Commit  string
	Depth   int
	Args    []string
	// PreCheckoutPatch is an absolute layer-relative input path for git-clone.
	PreCheckoutPatch string
	// PreCheckoutScript is an absolute layer-relative path to the clone hook.
	PreCheckoutScript string
}

// Unit is one generated commit, defined by a manifest.
type Unit struct {
	ID         string
	Directory  string
	Message    []byte
	CoAuthors  []string
	Disabled   bool
	DependsOn  []string
	Operations []Operation
}

// Load reads the canonical repository rooted at root and rejects malformed or
// ambiguous layer definitions before a projection mutates Git state.
func Load(root string) (*Repository, error) {
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, fmt.Errorf("resolve repository root %q: %w", root, err)
	}

	// Do not silently reinterpret an old definition as a composition.
	if _, err := os.Lstat(filepath.Join(absRoot, "upstream.json")); err == nil {
		return nil, errors.New("upstream.json is no longer supported; define sources with git-clone in layer.toml")
	} else if !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("inspect upstream.json: %w", err)
	}

	layers, err := loadLayers(filepath.Join(absRoot, "layers"))
	if err != nil {
		return nil, err
	}
	if len(layers) == 0 {
		return nil, errors.New("at least one layer is required")
	}
	seen := make(map[string]Unit, len(layers))
	for _, unit := range layers {
		deps := map[string]bool{}
		for _, id := range unit.DependsOn {
			if err := ValidateLayerID(id); err != nil {
				return nil, fmt.Errorf("layer %q dependency: %w", unit.ID, err)
			}
			if deps[id] {
				return nil, fmt.Errorf("layer %q repeats dependency %q", unit.ID, id)
			}
			deps[id] = true
			dependency, ok := seen[id]
			if !ok {
				return nil, fmt.Errorf("layer %q dependency %q must be an existing earlier layer", unit.ID, id)
			}
			if !unit.Disabled && dependency.Disabled {
				return nil, fmt.Errorf("enabled layer %q depends on disabled layer %q", unit.ID, id)
			}
		}
		seen[unit.ID] = unit
	}

	return &Repository{
		Root:   absRoot,
		Layers: layers,
	}, nil
}

func loadLayers(path string) ([]Unit, error) {
	entries, err := os.ReadDir(path)
	if errors.Is(err, os.ErrNotExist) {
		return []Unit{}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("read layer directory %q: %w", path, err)
	}
	layers := make([]Unit, 0, len(entries))
	for _, entry := range entries {
		name := entry.Name()
		if !entry.IsDir() {
			return nil, fmt.Errorf("invalid layer entry %q", filepath.Join(path, name))
		}
		if err := ValidateLayerID(name); err != nil {
			return nil, fmt.Errorf("invalid layer entry %q: %w", filepath.Join(path, name), err)
		}
		directory := filepath.Join(path, name)
		unit, err := LoadUnit(name, directory)
		if err != nil {
			return nil, err
		}
		layers = append(layers, unit)
	}
	return layers, nil
}

// LoadUnit reads one layer directory, including an unpublished capture candidate.
// It validates the supported entries and loads overlay bytes without following links.
func LoadUnit(id, directory string) (Unit, error) {
	entries, err := os.ReadDir(directory)
	if err != nil {
		return Unit{}, fmt.Errorf("read layer %q: %w", id, err)
	}
	for _, entry := range entries {
		if entry.Name() == "layer.toml" {
			return loadManifest(id, directory, entries)
		}
	}
	return Unit{}, fmt.Errorf("layer %q is missing layer.toml", id)
}

func requireNonemptyRegularFile(entry os.DirEntry, path string) error {
	info, err := entry.Info()
	if err != nil {
		return fmt.Errorf("inspect layer file %q: %w", path, err)
	}
	if !info.Mode().IsRegular() || info.Size() == 0 {
		return fmt.Errorf("layer file %q must be a nonempty regular file", path)
	}
	return nil
}

// ValidateLayerID rejects names that cannot identify canonical layer directories.
func ValidateLayerID(id string) error {
	if !layerIDPattern.MatchString(id) {
		return fmt.Errorf("invalid layer ID %q", id)
	}
	return nil
}

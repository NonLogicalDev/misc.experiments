// Modified from abg-OAI/codex: manifest-based layer definitions added.
// Package definition reads and validates the canonical Saffrodex repository.
// It owns the on-disk layer representation, while projection and maintenance
// packages own operations performed with those definitions.
package definition

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
)

var layerIDPattern = regexp.MustCompile(`^[0-9]{4}-[a-z0-9]+(-[a-z0-9]+)*$`)

// FoundationLayerID identifies the required first generated commit.
const FoundationLayerID = "0000-foundation"

// Repository is one complete canonical Saffrodex definition.
// Layers are ordered lexically by their numbered directory names.
type Repository struct {
	Root     string
	Upstream Upstream
	Layers   []Unit
}

// Upstream identifies the annotated or lightweight release tag and the commit
// it must resolve to. Keeping both values detects a locally moved tag.
type Upstream struct {
	Tag    string `json:"tag"`
	Commit string `json:"commit"`
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

// Unit is one generated commit, in legacy or manifest form.
type Unit struct {
	ID          string
	Directory   string
	Message     []byte
	CoAuthors   []string
	Disabled    bool
	DependsOn   []string
	Operations  []Operation
	MessagePath string
	PatchPath   string
	Overlay     []OverlayEntry
}

// Load reads the canonical repository rooted at root and rejects malformed or
// ambiguous layer definitions before a projection mutates Git state.
func Load(root string) (*Repository, error) {
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, fmt.Errorf("resolve repository root %q: %w", root, err)
	}

	// An absent upstream file selects repository-neutral composition. A file
	// that exists but cannot be read or decoded must never select that mode.
	var upstream Upstream
	upstreamPath := filepath.Join(absRoot, "upstream.json")
	_, statErr := os.Lstat(upstreamPath)
	legacy := statErr == nil
	if statErr != nil && !errors.Is(statErr, os.ErrNotExist) {
		return nil, fmt.Errorf("inspect upstream definition: %w", statErr)
	}
	if legacy {
		upstream, err = loadUpstream(upstreamPath)
		if err != nil {
			return nil, err
		}
	}

	layers, err := loadLayers(filepath.Join(absRoot, "layers"))
	if err != nil {
		return nil, err
	}
	if len(layers) == 0 {
		return nil, errors.New("at least one layer is required")
	}
	if legacy && layers[0].ID != FoundationLayerID {
		return nil, fmt.Errorf("first layer must be %q", FoundationLayerID)
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
		Root:     absRoot,
		Upstream: upstream,
		Layers:   layers,
	}, nil
}

func loadUpstream(path string) (Upstream, error) {
	file, err := os.Open(path)
	if err != nil {
		return Upstream{}, fmt.Errorf("open %q: %w", path, err)
	}
	defer file.Close()

	var upstream Upstream
	decoder := json.NewDecoder(file)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&upstream); err != nil {
		return Upstream{}, fmt.Errorf("decode %q: %w", path, err)
	}
	if err := requireJSONEnd(decoder); err != nil {
		return Upstream{}, fmt.Errorf("decode %q: %w", path, err)
	}
	if upstream.Tag == "" {
		return Upstream{}, errors.New("upstream tag is required")
	}
	if upstream.Commit == "" {
		return Upstream{}, errors.New("upstream commit is required")
	}
	return upstream, nil
}

func requireJSONEnd(decoder *json.Decoder) error {
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("unexpected value after object")
		}
		return err
	}
	return nil
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
	unit := Unit{
		ID:          id,
		Directory:   directory,
		MessagePath: filepath.Join(directory, "COMMIT_EDITMSG"),
	}
	for _, entry := range entries {
		path := filepath.Join(directory, entry.Name())
		switch entry.Name() {
		case "COMMIT_EDITMSG":
			if err := requireNonemptyRegularFile(entry, path); err != nil {
				return Unit{}, err
			}
		case "patch":
			if err := requireNonemptyRegularFile(entry, path); err != nil {
				return Unit{}, err
			}
			unit.PatchPath = path
		case "overlay":
			if !entry.IsDir() {
				return Unit{}, fmt.Errorf("overlay %q must be a directory", path)
			}
			unit.Overlay, err = readOverlay(path)
			if err != nil {
				return Unit{}, err
			}
		default:
			return Unit{}, fmt.Errorf("invalid entry %q in layer %q", entry.Name(), id)
		}
	}
	if _, err := os.Stat(unit.MessagePath); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return Unit{}, fmt.Errorf("layer %q is missing COMMIT_EDITMSG", id)
		}
		return Unit{}, fmt.Errorf("inspect layer message %q: %w", unit.MessagePath, err)
	}
	return unit, nil
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

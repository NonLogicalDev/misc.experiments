// Modified from abg-OAI/codex: adds manifest-based layer definitions.
package definition

import (
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"github.com/BurntSushi/toml"
)

type manifest struct {
	VCS struct {
		CommitMessage string `toml:"commit-msg"`
	} `toml:"vcs"`
	Operations []struct {
		Patch *struct {
			File string `toml:"file"`
		} `toml:"patch"`
		Overlay *struct {
			Directory string `toml:"directory"`
		} `toml:"overlay"`
	} `toml:"operation"`
}

func loadManifest(id, directory string, entries []os.DirEntry) (Unit, error) {
	path := filepath.Join(directory, "layer.toml")
	for _, entry := range entries {
		switch entry.Name() {
		case "COMMIT_EDITMSG":
			return Unit{}, fmt.Errorf("layer %q mixes layer.toml and COMMIT_EDITMSG", id)
		case "layer.toml":
			if err := requireNonemptyRegularFile(entry, path); err != nil {
				return Unit{}, err
			}
		}
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return Unit{}, fmt.Errorf("read layer manifest %q: %w", path, err)
	}
	var m manifest
	metadata, err := toml.Decode(string(data), &m)
	if err != nil {
		return Unit{}, fmt.Errorf("decode layer manifest %q: %w", path, err)
	}
	if keys := metadata.Undecoded(); len(keys) != 0 {
		return Unit{}, fmt.Errorf("unknown layer manifest keys %v", keys)
	}
	if m.VCS.CommitMessage == "" {
		return Unit{}, fmt.Errorf("layer %q requires nonempty vcs.commit-msg", id)
	}
	if !utf8.ValidString(m.VCS.CommitMessage) || strings.ContainsRune(m.VCS.CommitMessage, 0) {
		return Unit{}, fmt.Errorf("layer %q commit message must be valid UTF-8 without NUL", id)
	}
	absDir, err := filepath.Abs(directory)
	if err != nil {
		return Unit{}, fmt.Errorf("resolve layer directory: %w", err)
	}
	unit := Unit{ID: id, Directory: absDir, Message: []byte(m.VCS.CommitMessage)}
	for i, operation := range m.Operations {
		if (operation.Patch == nil) == (operation.Overlay == nil) {
			return Unit{}, fmt.Errorf("layer %q operation %d must have exactly one supported operation type", id, i+1)
		}
		if operation.Patch != nil {
			resolved, err := manifestPath(absDir, operation.Patch.File, false)
			if err != nil {
				return Unit{}, fmt.Errorf("layer %q operation %d patch: %w", id, i+1, err)
			}
			unit.Operations = append(unit.Operations, Operation{Kind: "patch", Path: resolved})
		} else {
			resolved, err := manifestPath(absDir, operation.Overlay.Directory, true)
			if err != nil {
				return Unit{}, fmt.Errorf("layer %q operation %d overlay: %w", id, i+1, err)
			}
			additions, err := readOverlay(resolved)
			if err != nil {
				return Unit{}, fmt.Errorf("layer %q operation %d overlay: %w", id, i+1, err)
			}
			unit.Operations = append(unit.Operations, Operation{Kind: "overlay", Path: resolved, Overlay: additions})
		}
	}
	if err := rejectUnreferencedFiles(absDir, unit.Operations); err != nil {
		return Unit{}, fmt.Errorf("layer %q: %w", id, err)
	}
	return unit, nil
}

// Reject unreferenced content so a later capture or refresh cannot silently
// delete files that the manifest did not include in its generated commit.
func rejectUnreferencedFiles(directory string, operations []Operation) error {
	patches := map[string]bool{}
	overlays := map[string]bool{}
	parents := map[string]bool{".": true}
	for _, operation := range operations {
		relative, err := filepath.Rel(directory, operation.Path)
		if err != nil {
			return err
		}
		if relative == "layer.toml" {
			return fmt.Errorf("layer.toml cannot be an operation input")
		}
		if operation.Kind == "patch" {
			patches[relative] = true
		} else {
			overlays[relative] = true
		}
		for parent := filepath.Dir(relative); parent != "."; parent = filepath.Dir(parent) {
			parents[parent] = true
		}
	}
	return filepath.WalkDir(directory, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		relative, err := filepath.Rel(directory, path)
		if err != nil {
			return err
		}
		if relative == "layer.toml" {
			return nil
		}
		if overlays[relative] {
			return filepath.SkipDir
		}
		if patches[relative] || (entry.IsDir() && parents[relative]) {
			return nil
		}
		return fmt.Errorf("unreferenced layer entry %q", relative)
	})
}

// manifestPath rejects traversal and symlink components. Overlay contents can
// still include symlinks, which readOverlay stores as links rather than follows.
func manifestPath(directory, name string, wantDirectory bool) (string, error) {
	if name == "." || !fs.ValidPath(name) || !filepath.IsLocal(name) || strings.Contains(name, `\`) {
		return "", fmt.Errorf("invalid layer path %q", name)
	}
	current := directory
	parts := strings.Split(name, "/")
	for i, part := range parts {
		if strings.EqualFold(part, ".git") {
			return "", fmt.Errorf("layer path %q addresses Git metadata", name)
		}
		current = filepath.Join(current, part)
		info, err := os.Lstat(current)
		if err != nil {
			return "", fmt.Errorf("inspect %q: %w", name, err)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return "", fmt.Errorf("layer path %q includes a symlink", name)
		}
		if i < len(parts)-1 {
			if !info.IsDir() {
				return "", fmt.Errorf("layer path %q contains a non-directory", name)
			}
		} else if wantDirectory {
			if !info.IsDir() {
				return "", fmt.Errorf("layer path %q must be a directory", name)
			}
		} else if !info.Mode().IsRegular() || info.Size() == 0 {
			return "", fmt.Errorf("layer path %q must be a nonempty regular file", name)
		}
	}
	return current, nil
}

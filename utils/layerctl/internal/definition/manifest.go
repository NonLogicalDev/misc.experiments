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
	Layer struct {
		Enabled   *bool    `toml:"enabled"`
		DependsOn []string `toml:"depends-on"`
	} `toml:"layer"`
	VCS struct {
		CommitMessage string   `toml:"commit-msg"`
		CoAuthors     []string `toml:"co-authors"`
	} `toml:"vcs"`
	Operations []struct {
		Patch *struct {
			File string `toml:"file"`
		} `toml:"patch"`
		Overlay *struct {
			Directory string `toml:"directory"`
		} `toml:"overlay"`
		Script *struct {
			File string   `toml:"file"`
			Args []string `toml:"args"`
		} `toml:"script"`
		GitClone *struct {
			URL               *string `toml:"url"`
			Dir               *string `toml:"dir"`
			Ref               string  `toml:"ref"`
			Commit            string  `toml:"commit"`
			Depth             *int    `toml:"depth"`
			PreCheckoutPatch  *string `toml:"pre-checkout-patch"`
			PreCheckoutScript *string `toml:"pre-checkout-script"`
		} `toml:"git-clone"`
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
	for _, coAuthor := range m.VCS.CoAuthors {
		if err := ValidateCoAuthor(coAuthor); err != nil {
			return Unit{}, fmt.Errorf("layer %q: %w", id, err)
		}
	}
	unit := Unit{ID: id, Directory: absDir, Message: []byte(m.VCS.CommitMessage), CoAuthors: m.VCS.CoAuthors, DependsOn: m.Layer.DependsOn}
	if m.Layer.Enabled != nil {
		unit.Disabled = !*m.Layer.Enabled
	}
	for i, operation := range m.Operations {
		types := 0
		if operation.Patch != nil {
			types++
		}
		if operation.Overlay != nil {
			types++
		}
		if operation.GitClone != nil {
			types++
		}
		if operation.Script != nil {
			types++
		}
		if types != 1 {
			return Unit{}, fmt.Errorf("layer %q operation %d must have exactly one supported operation type", id, i+1)
		}
		if operation.Patch != nil {
			resolved, err := manifestPath(absDir, operation.Patch.File, false, false)
			if err != nil {
				return Unit{}, fmt.Errorf("layer %q operation %d patch: %w", id, i+1, err)
			}
			unit.Operations = append(unit.Operations, Operation{Kind: "patch", Path: resolved})
		} else if operation.Overlay != nil {
			resolved, err := manifestPath(absDir, operation.Overlay.Directory, true, false)
			if err != nil {
				return Unit{}, fmt.Errorf("layer %q operation %d overlay: %w", id, i+1, err)
			}
			additions, err := readOverlay(resolved)
			if err != nil {
				return Unit{}, fmt.Errorf("layer %q operation %d overlay: %w", id, i+1, err)
			}
			unit.Operations = append(unit.Operations, Operation{Kind: "overlay", Path: resolved, Overlay: additions})
		} else if operation.Script != nil {
			resolved, err := manifestPath(absDir, operation.Script.File, false, true)
			if err != nil {
				return Unit{}, fmt.Errorf("layer %q operation %d script: %w", id, i+1, err)
			}
			info, err := os.Lstat(resolved)
			if err != nil {
				return Unit{}, fmt.Errorf("inspect script: %w", err)
			}
			if info.Mode().Perm()&0111 == 0 {
				return Unit{}, fmt.Errorf("layer %q operation %d script must be executable", id, i+1)
			}
			for _, arg := range operation.Script.Args {
				if strings.ContainsRune(arg, 0) {
					return Unit{}, fmt.Errorf("layer %q operation %d script argument contains NUL", id, i+1)
				}
			}
			unit.Operations = append(unit.Operations, Operation{Kind: "script", Path: resolved, Args: operation.Script.Args})
		} else {
			clone := operation.GitClone
			if clone.URL == nil || strings.TrimSpace(*clone.URL) == "" || strings.ContainsRune(*clone.URL, 0) {
				return Unit{}, fmt.Errorf("layer %q operation %d git-clone requires a nonempty URL without NUL", id, i+1)
			}
			dir := ""
			if clone.Dir != nil {
				dir = *clone.Dir
			}
			if err := validateWorkspaceDir(dir); err != nil {
				return Unit{}, fmt.Errorf("layer %q operation %d git-clone: %w", id, i+1, err)
			}
			for name, value := range map[string]string{"ref": clone.Ref, "commit": clone.Commit} {
				if strings.ContainsRune(value, 0) || strings.HasPrefix(value, "-") {
					return Unit{}, fmt.Errorf("layer %q operation %d git-clone %s is invalid", id, i+1, name)
				}
			}
			depth := 0
			if clone.Depth != nil {
				if *clone.Depth <= 0 {
					return Unit{}, fmt.Errorf("layer %q operation %d git-clone depth must be positive", id, i+1)
				}
				depth = *clone.Depth
			}
			var preCheckoutPatch string
			if clone.PreCheckoutPatch != nil {
				preCheckoutPatch, err = manifestPath(absDir, *clone.PreCheckoutPatch, false, false)
				if err != nil {
					return Unit{}, fmt.Errorf("layer %q operation %d git-clone pre-checkout-patch: %w", id, i+1, err)
				}
				if preCheckoutPatch == filepath.Join(absDir, "layer.toml") {
					return Unit{}, fmt.Errorf("layer.toml cannot be an operation input")
				}
			}
			var preCheckoutScript string
			if clone.PreCheckoutScript != nil {
				preCheckoutScript, err = manifestPath(absDir, *clone.PreCheckoutScript, false, false)
				if err != nil {
					return Unit{}, fmt.Errorf("layer %q operation %d git-clone pre-checkout-script: %w", id, i+1, err)
				}
				if preCheckoutScript == filepath.Join(absDir, "layer.toml") {
					return Unit{}, fmt.Errorf("layer.toml cannot be an operation input")
				}
				info, err := os.Lstat(preCheckoutScript)
				if err != nil {
					return Unit{}, fmt.Errorf("inspect pre-checkout script: %w", err)
				}
				if info.Mode().Perm()&0111 == 0 {
					return Unit{}, fmt.Errorf("layer %q operation %d git-clone pre-checkout-script must be executable", id, i+1)
				}
			}
			unit.Operations = append(unit.Operations, Operation{Kind: "git-clone", URL: *clone.URL, Dir: dir, Ref: clone.Ref, Commit: clone.Commit, Depth: depth, PreCheckoutPatch: preCheckoutPatch, PreCheckoutScript: preCheckoutScript})
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
	for _, operation := range operations {
		if operation.Kind == "script" || operation.PreCheckoutScript != "" {
			return validateScriptSupportFiles(directory)
		}
	}
	patches := map[string]bool{}
	overlays := map[string]bool{}
	parents := map[string]bool{".": true}
	for _, operation := range operations {
		if operation.Kind == "git-clone" {
			if operation.PreCheckoutPatch == "" {
				continue
			}
			operation.Path = operation.PreCheckoutPatch
			operation.Kind = "patch"
		}
		relative, err := filepath.Rel(directory, operation.Path)
		if err != nil {
			return err
		}
		if relative == "layer.toml" {
			return fmt.Errorf("layer.toml cannot be an operation input")
		}
		if operation.Kind == "patch" || operation.Kind == "script" {
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

// Script operations can read helper files relative to their layer directory.
// Walk without following symlinks and reject files that refresh cannot copy.
func validateScriptSupportFiles(directory string) error {
	return filepath.WalkDir(directory, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if info.IsDir() || info.Mode().IsRegular() || info.Mode()&os.ModeSymlink != 0 {
			return nil
		}
		rel, err := filepath.Rel(directory, path)
		if err != nil {
			return err
		}
		return fmt.Errorf("unsupported script support file %q", rel)
	})
}

// manifestPath rejects traversal and symlink components. Overlay contents can
// still include symlinks, which readOverlay stores as links rather than follows.
func manifestPath(directory, name string, wantDirectory, allowEmpty bool) (string, error) {
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
		} else if !info.Mode().IsRegular() || (!allowEmpty && info.Size() == 0) {
			return "", fmt.Errorf("layer path %q must be a nonempty regular file", name)
		}
	}
	return current, nil
}

// validateWorkspaceDir checks the lexical destination only. Execution must
// independently check filesystem symlinks and occupancy in the workspace.
func validateWorkspaceDir(dir string) error {
	if dir == "" {
		return nil
	}
	if !fs.ValidPath(dir) || dir == "." || !filepath.IsLocal(dir) || strings.Contains(dir, `\`) || strings.ContainsRune(dir, 0) || (len(dir) >= 2 && dir[1] == ':' && ((dir[0] >= 'a' && dir[0] <= 'z') || (dir[0] >= 'A' && dir[0] <= 'Z'))) {
		return fmt.Errorf("invalid workspace directory %q", dir)
	}
	for _, component := range strings.Split(dir, "/") {
		if strings.EqualFold(component, ".git") {
			return fmt.Errorf("workspace directory %q addresses Git metadata", dir)
		}
	}
	return nil
}

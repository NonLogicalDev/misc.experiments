// Modified from abg-OAI/codex: module import path changed for this extraction.
// Package layer captures accepted projection commits as canonical
// layer definitions.
package layer

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"unicode/utf8"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/layercommit"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
)

// Service owns updates to the canonical layers directory.
type Service struct {
	Definition *definition.Repository // required
	Git        *gitrepo.Repository    // required
	Projection interface {
		Get(context.Context, string) (projection.Projection, error)
	} // required
}

// AddRequest describes a new numbered layer captured from a projection.
type AddRequest struct {
	ID         string
	Projection string
}

// Add captures a projection's editable range as a new canonical layer.
func (s *Service) Add(ctx context.Context, req AddRequest) error {
	if err := definition.ValidateLayerID(req.ID); err != nil {
		return err
	}
	if slices.ContainsFunc(s.Definition.Layers, func(unit definition.Unit) bool { return unit.ID == req.ID }) {
		return fmt.Errorf("layer %q already exists", req.ID)
	}
	position, _ := slices.BinarySearchFunc(s.Definition.Layers, req.ID, func(unit definition.Unit, id string) int {
		return strings.Compare(unit.ID, id)
	})
	if position == 0 {
		return fmt.Errorf("new layer %q requires an enabled predecessor", req.ID)
	}
	source, err := s.Projection.Get(ctx, req.Projection)
	if err != nil {
		return err
	}
	if source.WorktreePath != "" {
		workspaceGit, err := gitrepo.Discover(ctx, source.WorktreePath)
		if err != nil {
			return fmt.Errorf("open projection repository: %w", err)
		}
		copy := *s
		copy.Git = workspaceGit
		s = &copy
	}
	if source.Base == source.Head {
		return fmt.Errorf("projection %q has no changes to capture", req.Projection)
	}
	previous := position - 1
	for previous >= 0 && s.Definition.Layers[previous].Disabled {
		previous--
	}
	if previous < 0 {
		return fmt.Errorf("new layer %q requires an enabled predecessor", req.ID)
	}
	predecessor := s.Definition.Layers[previous]
	if composer, ok := s.Projection.(interface {
		Through(context.Context, string) (string, error)
	}); ok {
		through, err := composer.Through(ctx, req.Projection)
		if err != nil {
			return err
		}
		if through != predecessor.ID {
			return fmt.Errorf("projection %q was created through %q, not the enabled predecessor %q", req.Projection, through, predecessor.ID)
		}
	}
	if err := s.Git.Run(ctx, s.Git.Root, "merge-base", "--is-ancestor", source.Base, source.Head); err != nil {
		return fmt.Errorf("projection %q head must descend from its base: %w", req.Projection, err)
	}
	merges, err := s.Git.Output(ctx, s.Git.Root, "rev-list", "--merges", source.Base+".."+source.Head)
	if err != nil {
		return fmt.Errorf("inspect projection ancestry: %w", err)
	}
	if merges != "" {
		return fmt.Errorf("projection %q contains merge commits that capture would flatten; represent source imports with git-clone operations", req.Projection)
	}
	if err := s.requireGeneratedUnit(ctx, source.Base, predecessor); err != nil {
		return fmt.Errorf("projection %q base: %w", req.Projection, err)
	}
	return s.writeLayer(ctx, req.ID, source.Base, source.Head, false)
}

func (s *Service) findUnit(id string) *definition.Unit {
	for i := range s.Definition.Layers {
		if s.Definition.Layers[i].ID == id {
			return &s.Definition.Layers[i]
		}
	}
	return nil
}

func (s *Service) requireGeneratedUnit(ctx context.Context, commit string, unit definition.Unit) error {
	matches, err := s.isGeneratedUnit(ctx, commit, unit)
	if err != nil {
		return err
	}
	if !matches {
		return fmt.Errorf("generated commit is not unit %q", unit.ID)
	}
	return nil
}

func (s *Service) isGeneratedUnit(ctx context.Context, commit string, unit definition.Unit) (bool, error) {
	message, err := commitMessage(s.Git, ctx, s.Git.Root, commit)
	if err != nil {
		return false, err
	}
	layers := &layercommit.Service{Git: s.Git}
	wantMessage, err := layers.Message(unit)
	if err != nil {
		return false, err
	}
	return bytes.Equal(message, wantMessage), nil
}

func (s *Service) writeLayer(ctx context.Context, id, before, after string, replaceExisting bool) error {
	layersRoot := filepath.Join(s.Definition.Root, "layers")
	layers := &layercommit.Service{Git: s.Git}
	captured, err := layers.Capture(ctx, layercommit.CaptureRequest{
		Before: before,
		After:  after,
	})
	if err != nil {
		return err
	}

	temporaryPath, err := os.MkdirTemp(layersRoot, ".layerctl-"+id+"-")
	if err != nil {
		return fmt.Errorf("create temporary layer directory: %w", err)
	}
	defer os.RemoveAll(temporaryPath)
	var metadata *definition.Unit
	if replaceExisting {
		metadata = s.findUnit(id)
	}
	if err := writeManifestLayer(temporaryPath, captured, metadata); err != nil {
		return fmt.Errorf("write captured layer %q: %w", id, err)
	}
	temporaryUnit, err := definition.LoadUnit(id, temporaryPath)
	if err != nil {
		return fmt.Errorf("read captured layer %q: %w", id, err)
	}
	matches, err := layers.Matches(ctx, temporaryUnit, before, after)
	if err != nil {
		return fmt.Errorf("verify captured layer %q: %w", id, err)
	}
	if !matches {
		return fmt.Errorf("captured layer %q does not reproduce the accepted commit", id)
	}

	return installLayer(layersRoot, id, temporaryPath, replaceExisting)
}

// writeManifestLayer writes an exact UTF-8 commit message and the canonical
// patch-then-overlay representation produced by Capture.
func writeManifestLayer(directory string, captured layercommit.Captured, metadata *definition.Unit) error {
	if len(captured.Message) == 0 || !utf8.Valid(captured.Message) || bytes.ContainsRune(captured.Message, 0) {
		return fmt.Errorf("commit message must be nonempty UTF-8 without NUL")
	}
	var manifest bytes.Buffer
	if metadata != nil && (metadata.Disabled || metadata.DependsOn != nil) {
		manifest.WriteString("[layer]\n")
		if metadata.Disabled {
			manifest.WriteString("enabled = false\n")
		}
		if metadata.DependsOn != nil {
			dependencies, err := json.Marshal(metadata.DependsOn)
			if err != nil {
				return err
			}
			fmt.Fprintf(&manifest, "depends-on = %s\n", dependencies)
		}
		manifest.WriteByte('\n')
	}
	fmt.Fprintf(&manifest, "[vcs]\ncommit-msg = %s\n", multilineMessage(string(captured.Message)))
	if metadata != nil && len(metadata.CoAuthors) > 0 {
		authors, err := json.Marshal(metadata.CoAuthors)
		if err != nil {
			return err
		}
		fmt.Fprintf(&manifest, "co-authors = %s\n", authors)
	}
	if len(captured.Patch) > 0 {
		manifest.WriteString("\n[[operation]]\n[operation.patch]\nfile = \"patch\"\n")
		if err := os.WriteFile(filepath.Join(directory, "patch"), captured.Patch, 0o644); err != nil {
			return err
		}
	}
	if len(captured.Overlay) > 0 {
		manifest.WriteString("\n[[operation]]\n[operation.overlay]\ndirectory = \"overlay\"\n")
		if err := definition.WriteOverlay(directory, captured.Overlay); err != nil {
			return err
		}
	}
	return os.WriteFile(filepath.Join(directory, "layer.toml"), manifest.Bytes(), 0o644)
}

func installLayer(layersRoot, id, temporaryPath string, replaceExisting bool) error {
	target := filepath.Join(layersRoot, id)
	if !replaceExisting {
		if err := os.Rename(temporaryPath, target); err != nil {
			return fmt.Errorf("install layer %q: %w", id, err)
		}
		return nil
	}
	backupPath, err := os.MkdirTemp(layersRoot, ".layerctl-backup-"+id+"-")
	if err != nil {
		return fmt.Errorf("reserve layer backup: %w", err)
	}
	if err := os.Remove(backupPath); err != nil {
		return fmt.Errorf("prepare layer backup: %w", err)
	}
	if err := os.Rename(target, backupPath); err != nil {
		return fmt.Errorf("backup layer %q: %w", id, err)
	}
	if err := os.Rename(temporaryPath, target); err != nil {
		if rollbackErr := os.Rename(backupPath, target); rollbackErr != nil {
			return fmt.Errorf("install refreshed layer %q: %w; restore backup %q: %v", id, err, backupPath, rollbackErr)
		}
		return fmt.Errorf("install refreshed layer %q: %w", id, err)
	}
	if err := os.RemoveAll(backupPath); err != nil {
		return fmt.Errorf("remove layer backup %q: %w", backupPath, err)
	}
	return nil
}

func commitMessage(git *gitrepo.Repository, ctx context.Context, root, commit string) ([]byte, error) {
	object, err := git.Bytes(ctx, root, "cat-file", "commit", commit)
	if err != nil {
		return nil, fmt.Errorf("read commit %q: %w", commit, err)
	}
	_, message, ok := bytes.Cut(object, []byte("\n\n"))
	if !ok || len(message) == 0 {
		return nil, fmt.Errorf("commit %q has no message", commit)
	}
	return message, nil
}

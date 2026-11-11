package projection

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/composition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/layercommit"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/scriptop"
)

// CompositionConflictError identifies a recoverable operation conflict. The
// workspace remains owned and registered for the user to resolve and continue.
type CompositionConflictError struct {
	Name, Workspace, Layer string
	Operation              int
	Cause                  error
}

func (e *CompositionConflictError) Error() string {
	return fmt.Sprintf("layer %q operation %d requires resolution in %q: %v; resolve it then run layerctl projection continue %s", e.Layer, e.Operation, e.Workspace, e.Cause, e.Name)
}
func (e *CompositionConflictError) Unwrap() error { return e.Cause }

type fingerprintOperation struct {
	Kind, URL, Dir, Ref, Commit string
	Args                        []string
	Depth                       int
	Patch                       []byte
	Overlay                     []definition.OverlayEntry
}
type fingerprintAsset struct {
	Path string
	Mode uint32
	Data []byte
	Link string
}

type fingerprintUnit struct {
	AssetDigest string
	ID          string
	Message     []byte
	Operations  []fingerprintOperation
	DependsOn   []string
	CoAuthors   []string
}

func fingerprintUnits(units []definition.Unit) (string, error) {
	layers := make([]fingerprintUnit, 0, len(units))
	for _, u := range units {
		msg := u.Message
		if msg == nil {
			var err error
			msg, err = os.ReadFile(u.MessagePath)
			if err != nil {
				return "", err
			}
		}
		f := fingerprintUnit{ID: u.ID, Message: msg, DependsOn: u.DependsOn, CoAuthors: u.CoAuthors}
		if u.Message == nil {
			op := fingerprintOperation{Kind: "legacy", Overlay: u.Overlay}
			if u.PatchPath != "" {
				var err error
				op.Patch, err = os.ReadFile(u.PatchPath)
				if err != nil {
					return "", err
				}
			}
			f.Operations = append(f.Operations, op)
		} else {
			for _, o := range u.Operations {
				op := fingerprintOperation{Kind: o.Kind, URL: o.URL, Dir: o.Dir, Ref: o.Ref, Commit: o.Commit, Depth: o.Depth, Args: o.Args, Overlay: o.Overlay}
				if o.Kind == "patch" || o.Kind == "script" {
					var err error
					op.Patch, err = os.ReadFile(o.Path)
					if err != nil {
						return "", err
					}
				}
				f.Operations = append(f.Operations, op)
			}
		}
		// Scripts may read any supporting file within their layer directory.
		// Bind recovery to the whole directory without following symlinks.
		for _, op := range u.Operations {
			if op.Kind == "script" {
				var err error
				f.AssetDigest, err = FingerprintScriptAssets(u.Directory)
				if err != nil {
					return "", fmt.Errorf("fingerprint script layer %q: %w", u.ID, err)
				}
				break
			}
		}
		layers = append(layers, f)
	}
	data, err := json.Marshal(layers)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
}

// FingerprintScriptAssets binds trusted script support files to their layer.
// Symlinks are recorded as links; their external targets are not followed.
func FingerprintScriptAssets(directory string) (string, error) {
	assets, err := fingerprintLayerFiles(directory)
	if err != nil {
		return "", err
	}
	data, err := json.Marshal(assets)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
}

// fingerprintLayerFiles includes names, permission and type bits, file bytes,
// and symlink targets. WalkDir never follows symlinks; external targets remain
// outside this snapshot, like other external effects of trusted scripts.
func fingerprintLayerFiles(directory string) ([]fingerprintAsset, error) {
	if directory == "" {
		return nil, errors.New("script layer directory is required")
	}
	rootInfo, err := os.Lstat(directory)
	if err != nil {
		return nil, err
	}
	if !rootInfo.IsDir() || rootInfo.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("script layer root must be a real directory")
	}
	var assets []fingerprintAsset
	err = filepath.WalkDir(directory, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, err := filepath.Rel(directory, path)
		if err != nil {
			return err
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		asset := fingerprintAsset{Path: filepath.ToSlash(rel), Mode: uint32(info.Mode())}
		switch {
		case info.Mode()&os.ModeSymlink != 0:
			asset.Link, err = os.Readlink(path)
		case info.IsDir():
		case info.Mode().IsRegular():
			asset.Data, err = os.ReadFile(path)
		default:
			return fmt.Errorf("unsupported script layer entry %q", asset.Path)
		}
		if err != nil {
			return err
		}
		assets = append(assets, asset)
		return nil
	})
	if err != nil {
		return nil, err
	}
	return assets, nil
}

func saveCompositionRecord(dir string, record compositionRecord) error {
	data, err := json.Marshal(record)
	if err != nil {
		return err
	}
	f, err := os.CreateTemp(dir, ".record-")
	if err != nil {
		return fmt.Errorf("create composition record: %w", err)
	}
	defer os.Remove(f.Name())
	if _, err := f.Write(data); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		_ = f.Close()
		return err
	}
	if err := f.Close(); err != nil {
		return err
	}
	return os.Rename(f.Name(), filepath.Join(dir, "record.json"))
}

func (s *CompositionService) selectedCompositionUnits(through string) ([]definition.Unit, error) {
	var units []definition.Unit
	included := map[string]bool{}
	found := through == ""
	for _, u := range s.Definition.Layers {
		if u.Disabled {
			if u.ID == through {
				return nil, fmt.Errorf("terminal layer %q is disabled", through)
			}
			continue
		}
		for _, dependency := range u.DependsOn {
			if !included[dependency] {
				return nil, fmt.Errorf("layer %q requires unavailable preceding layer %q", u.ID, dependency)
			}
		}
		included[u.ID] = true
		units = append(units, u)
		if u.ID == through {
			found = true
			break
		}
	}
	if !found {
		return nil, fmt.Errorf("terminal layer %q is not present", through)
	}
	if len(units) == 0 {
		return nil, errors.New("no enabled layers to compose")
	}
	return units, nil
}

func (s *CompositionService) recordDir(ctx context.Context, name string) (string, error) {
	store, err := s.storage(ctx)
	if err != nil {
		return "", err
	}
	return filepath.Join(store, name), nil
}

// Continue stages the user's resolution, then resumes later operations. It
// refuses ambiguous interrupted steps and changed definitions or HEAD.
func (s *CompositionService) Continue(ctx context.Context, name string) (Projection, error) {
	release, err := s.acquireCompositionLock(ctx, name)
	if err != nil {
		return Projection{}, err
	}
	defer release()
	record, err := s.readRecord(ctx, name)
	if err != nil {
		return Projection{}, err
	}
	if record.Creating {
		return Projection{}, fmt.Errorf("composition %q creation was interrupted; inspect %q and delete the projection before retrying", name, record.Workspace)
	}
	if err := verifyComposition(record); err != nil {
		return Projection{}, fmt.Errorf("composition %q: %w", name, err)
	}
	if record.Complete {
		return s.Get(ctx, name)
	}
	through := record.Through
	if record.AllLayers {
		through = ""
	}
	units, err := s.selectedCompositionUnits(through)
	if err != nil {
		return Projection{}, err
	}
	digest, err := fingerprintUnits(units)
	if err != nil {
		return Projection{}, err
	}
	if digest != record.Fingerprint {
		return Projection{}, errors.New("composition definitions changed; restore them or delete the projection")
	}
	if record.UnitIndex < 0 || record.UnitIndex > len(units) {
		return Projection{}, errors.New("invalid composition layer index")
	}
	layers := &layercommit.Service{Git: &gitrepo.Repository{Root: record.Workspace}}
	if record.UnitIndex == len(units) {
		if record.StepIndex != 0 || record.Resolving || record.StepInProgress || record.CommitInProgress {
			return Projection{}, errors.New("invalid completed composition progress")
		}
	} else {
		count := layers.StepCount(units[record.UnitIndex])
		if record.StepIndex < 0 || record.StepIndex > count || (record.Resolving && record.StepIndex == count) {
			return Projection{}, errors.New("invalid composition operation index")
		}
	}
	if record.StepInProgress || record.CommitInProgress {
		return Projection{}, errors.New("a composition operation was interrupted and its outcome is uncertain; delete the projection before retrying")
	}

	git := &gitrepo.Repository{Root: record.Workspace}
	actual, headErr := git.Output(ctx, record.Workspace, "rev-parse", "--verify", "HEAD^{commit}")
	if (record.Head == "" && headErr == nil) || (record.Head != "" && (headErr != nil || actual != record.Head)) {
		return Projection{}, errors.New("composition HEAD changed; delete the projection before retrying")
	}
	dir, err := s.recordDir(ctx, name)
	if err != nil {
		return Projection{}, err
	}
	if record.Resolving {
		record.StepInProgress = true
		if err := saveCompositionRecord(dir, record); err != nil {
			return Projection{}, err
		}
		if err := git.Run(ctx, record.Workspace, "add", "-A"); err != nil {
			return Projection{}, fmt.Errorf("stage resolved operation; its outcome is uncertain: %w", err)
		}
		record.StepInProgress = false
		record.Resolving = false
		record.StepIndex++
		if err := saveCompositionRecord(dir, record); err != nil {
			return Projection{}, err
		}
	}
	return s.runComposition(ctx, dir, &record, units)
}

func (s *CompositionService) runComposition(ctx context.Context, dir string, record *compositionRecord, units []definition.Unit) (Projection, error) {
	git := &gitrepo.Repository{Root: record.Workspace}
	layers := &layercommit.Service{Git: git}
	result := func() Projection {
		return Projection{Name: record.Name, Base: record.Base, Head: record.Head, WorktreePath: record.Workspace}
	}
	for record.UnitIndex < len(units) {
		unit := units[record.UnitIndex]
		if s.Log != nil {
			s.Log.Printf("applying %s", unit.ID)
		}
		if record.StepIndex == 0 && len(record.Parents) == 0 && record.Head != "" {
			record.Parents = append(record.Parents, record.Head)
		}
		for record.StepIndex < layers.StepCount(unit) {
			index := record.StepIndex
			record.StepInProgress = true
			if err := saveCompositionRecord(dir, *record); err != nil {
				return result(), err
			}
			var err error
			if unit.Message != nil && unit.Operations[index].Kind == "git-clone" {
				op := unit.Operations[index]
				var source string
				source, err = composition.Import(ctx, record.Workspace, composition.CloneRequest{URL: op.URL, Dir: op.Dir, Ref: op.Ref, Commit: op.Commit, Depth: op.Depth})
				if err == nil {
					duplicate := false
					for _, p := range record.Parents {
						if p == source {
							duplicate = true
							break
						}
					}
					if !duplicate {
						record.Parents = append(record.Parents, source)
					}
				}
			} else if unit.Message != nil && unit.Operations[index].Kind == "script" {
				err = scriptop.Run(ctx, record.Workspace, s.Definition.Root, unit.ID, unit.Directory, index, unit.Operations[index])
			} else {
				err = layers.ApplyStep(ctx, record.Workspace, unit, index)
			}
			if err != nil {
				// A failed script can already have arbitrary external side effects;
				// do not treat it as a Git conflict that can be skipped on resume.
				if unit.Message != nil && unit.Operations[index].Kind == "script" {
					return result(), fmt.Errorf("layer %q script operation %d failed; workspace %q is retained, delete the projection before retrying: %w", unit.ID, index+1, record.Workspace, err)
				}
				hasConflicts, inspectErr := layers.HasConflicts(ctx, record.Workspace)
				if inspectErr != nil {
					return result(), errors.Join(err, inspectErr)
				}
				var collision *layercommit.OverlayCollisionError
				if hasConflicts || errors.As(err, &collision) {
					record.StepInProgress = false
					record.Resolving = true
					if saveErr := saveCompositionRecord(dir, *record); saveErr != nil {
						return result(), errors.Join(err, saveErr)
					}
					return result(), &CompositionConflictError{Name: record.Name, Workspace: record.Workspace, Layer: unit.ID, Operation: index + 1, Cause: err}
				}
				return result(), fmt.Errorf("layer %q operation %d failed; workspace %q is retained, delete the projection before retrying: %w", unit.ID, index+1, record.Workspace, err)
			}
			record.StepIndex++
			record.StepInProgress = false
			if err := saveCompositionRecord(dir, *record); err != nil {
				return result(), err
			}
		}
		record.CommitInProgress = true
		if err := saveCompositionRecord(dir, *record); err != nil {
			return result(), err
		}
		tree, err := git.Output(ctx, record.Workspace, "write-tree")
		if err != nil {
			return result(), fmt.Errorf("write layer %q tree: %w", unit.ID, err)
		}
		message, err := layers.Message(unit)
		if err != nil {
			return result(), err
		}
		args := []string{"commit-tree", tree}
		for _, p := range record.Parents {
			args = append(args, "-p", p)
		}
		commit, err := git.Invoke(ctx, record.Workspace, gitrepo.Invocation{Arguments: args, Stdin: message})
		if err != nil {
			return result(), fmt.Errorf("commit layer %q: %w", unit.ID, err)
		}
		head := strings.TrimSpace(string(commit))
		if err := git.Run(ctx, record.Workspace, "update-ref", "HEAD", head); err != nil {
			return result(), fmt.Errorf("advance layer %q: %w", unit.ID, err)
		}
		record.Head = head
		record.UnitIndex++
		record.StepIndex = 0
		record.Parents = nil
		record.CommitInProgress = false
		if err := saveCompositionRecord(dir, *record); err != nil {
			return result(), err
		}
	}
	record.Complete = true
	record.Base = record.Head
	if err := saveCompositionRecord(dir, *record); err != nil {
		return result(), err
	}
	return result(), nil
}

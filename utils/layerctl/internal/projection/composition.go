package projection

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
)

// CompositionService owns independent workspace repositories. The Git object
// database is deliberately separate from the definition repository: importing
// a shallow source must not change the definition repository's history.
type CompositionService struct {
	Definition *definition.Repository
	Git        *gitrepo.Repository
	Log        *log.Logger
}

type compositionRecord struct {
	Name             string   `json:"name"`
	Workspace        string   `json:"workspace"`
	Token            string   `json:"token"`
	Base             string   `json:"base"`
	Through          string   `json:"through"`
	AllLayers        bool     `json:"allLayers,omitempty"`
	Fingerprint      string   `json:"fingerprint"`
	Head             string   `json:"head,omitempty"`
	UnitIndex        int      `json:"unitIndex"`
	StepIndex        int      `json:"stepIndex"`
	Parents          []string `json:"parents,omitempty"`
	StepInProgress   bool     `json:"stepInProgress,omitempty"`
	Resolving        bool     `json:"resolving,omitempty"`
	CommitInProgress bool     `json:"commitInProgress,omitempty"`
	Complete         bool     `json:"complete,omitempty"`
	Creating         bool     `json:"creating,omitempty"`
}

func (s *CompositionService) storage(ctx context.Context) (string, error) {
	common, err := s.Git.Output(ctx, s.Git.Root, "rev-parse", "--git-common-dir")
	if err != nil {
		return "", fmt.Errorf("resolve definition Git directory: %w", err)
	}
	if !filepath.IsAbs(common) {
		common = filepath.Join(s.Git.Root, common)
	}
	return filepath.Join(common, "layerctl", "compositions"), nil
}

// Create constructs a new owned workspace, applying layers in order. It never
// reuses an existing destination; an unsuccessful creation removes only the
// directory it created. Each layer records the previous workspace commit first,
// then each imported source commit as a merge parent.
func (s *CompositionService) Create(ctx context.Context, req CreateRequest) (Projection, error) {
	name, err := parseName(req.Name)
	if err != nil {
		return Projection{}, err
	}
	if s.Definition == nil || s.Git == nil {
		return Projection{}, errors.New("composition requires definition and Git repository")
	}
	units, err := s.selectedCompositionUnits(req.Through)
	if err != nil {
		return Projection{}, err
	}
	// Avoid colliding with the original projection namespace.
	if err := (&Service{Git: s.Git}).requireAbsent(ctx, name); err != nil {
		return Projection{}, err
	}
	store, err := s.storage(ctx)
	if err != nil {
		return Projection{}, err
	}
	if err := os.MkdirAll(store, 0700); err != nil {
		return Projection{}, fmt.Errorf("create composition directory: %w", err)
	}
	recordDir := filepath.Join(store, name)
	if err := os.Mkdir(recordDir, 0700); err != nil {
		return Projection{}, fmt.Errorf("reserve composition %q: %w", name, err)
	}
	keep := false
	var workspace string
	var workspaceCreated bool
	defer func() {
		if !keep {
			if workspaceCreated {
				_ = os.RemoveAll(workspace)
			}
			_ = os.RemoveAll(recordDir)
		}
	}()
	release, err := s.acquireCompositionLock(ctx, name)
	if err != nil {
		return Projection{}, err
	}
	defer release()
	if req.WorktreePath == "" {
		workspace = filepath.Join(recordDir, "workspace")
	} else {
		workspace, err = filepath.Abs(req.WorktreePath)
		if err != nil {
			return Projection{}, fmt.Errorf("resolve workspace path: %w", err)
		}
	}
	var tokenBytes [24]byte
	if _, err := rand.Read(tokenBytes[:]); err != nil {
		return Projection{}, fmt.Errorf("create workspace identity: %w", err)
	}
	token := hex.EncodeToString(tokenBytes[:])
	fingerprint, err := fingerprintUnits(units)
	if err != nil {
		return Projection{}, err
	}
	// Persist destination and identity before creating anything there. A crash
	// can leave an unverified directory, but recovery must never delete it.
	record := compositionRecord{Name: name, Workspace: workspace, Token: token, Through: units[len(units)-1].ID, AllLayers: req.Through == "", Fingerprint: fingerprint, Creating: true}
	if err := saveCompositionRecord(recordDir, record); err != nil {
		return Projection{}, err
	}
	keep = true
	if err := os.Mkdir(workspace, 0755); err != nil {
		// Mkdir did not create the requested path: discard only our reservation.
		keep = false
		return Projection{}, fmt.Errorf("create new workspace %q: %w", workspace, err)
	}
	workspaceCreated = true
	git := &gitrepo.Repository{Root: workspace}
	if err := git.Run(ctx, workspace, "init", "-q"); err != nil {
		return Projection{}, fmt.Errorf("initialize workspace %q; inspect it before deleting this projection: %w", workspace, err)
	}
	if err := os.WriteFile(filepath.Join(workspace, ".git", "layerctl-owner"), []byte(token), 0600); err != nil {
		return Projection{}, fmt.Errorf("write workspace marker in %q; inspect it before deleting this projection: %w", workspace, err)
	}
	record.Creating = false
	if err := saveCompositionRecord(recordDir, record); err != nil {
		return Projection{}, err
	}

	return s.runComposition(ctx, recordDir, &record, units)

}

func (s *CompositionService) readRecord(ctx context.Context, rawName string) (compositionRecord, error) {
	name, err := parseName(rawName)
	if err != nil {
		return compositionRecord{}, err
	}
	store, err := s.storage(ctx)
	if err != nil {
		return compositionRecord{}, err
	}
	data, err := os.ReadFile(filepath.Join(store, name, "record.json"))
	if err != nil {
		return compositionRecord{}, fmt.Errorf("read composition %q: %w", name, err)
	}
	var record compositionRecord
	if err := json.Unmarshal(data, &record); err != nil {
		return compositionRecord{}, fmt.Errorf("decode composition %q: %w", name, err)
	}
	if record.Name != name || record.Token == "" || !filepath.IsAbs(record.Workspace) {
		return compositionRecord{}, fmt.Errorf("invalid composition record %q", name)
	}
	return record, nil
}

func verifyComposition(record compositionRecord) error {
	info, err := os.Lstat(record.Workspace)
	if err != nil {
		return fmt.Errorf("inspect workspace: %w", err)
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("workspace is not a directory")
	}
	info, err = os.Lstat(filepath.Join(record.Workspace, ".git"))
	if err != nil {
		return fmt.Errorf("inspect workspace Git directory: %w", err)
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("workspace Git directory is not owned")
	}
	data, err := os.ReadFile(filepath.Join(record.Workspace, ".git", "layerctl-owner"))
	if err != nil {
		return fmt.Errorf("read workspace ownership: %w", err)
	}
	if string(data) != record.Token {
		return errors.New("workspace ownership does not match")
	}
	return nil
}

// Get returns the recorded base and live workspace HEAD.
func (s *CompositionService) Get(ctx context.Context, name string) (Projection, error) {
	record, err := s.readRecord(ctx, name)
	if err != nil {
		return Projection{}, err
	}
	if record.Creating {
		return Projection{}, fmt.Errorf("composition %q creation is incomplete; inspect %q and delete the projection before retrying", name, record.Workspace)
	}
	if err := verifyComposition(record); err != nil {
		return Projection{}, fmt.Errorf("composition %q: %w", name, err)
	}
	git := &gitrepo.Repository{Root: record.Workspace}
	head, err := git.Output(ctx, record.Workspace, "rev-parse", "--verify", "HEAD^{commit}")
	if err != nil {
		if record.Head != "" || record.Complete {
			return Projection{}, fmt.Errorf("read composition %q HEAD: %w", name, err)
		}
		head = ""
	}
	return Projection{Name: name, Base: record.Base, Head: head, WorktreePath: record.Workspace}, nil
}

// Through identifies the final layer used when the workspace was created.
func (s *CompositionService) Through(ctx context.Context, name string) (string, error) {
	record, err := s.readRecord(ctx, name)
	if err != nil {
		return "", err
	}
	if err := verifyComposition(record); err != nil {
		return "", err
	}
	if record.Through == "" {
		return "", errors.New("composition lacks its terminal layer identity")
	}
	return record.Through, nil
}

func (s *CompositionService) Path(ctx context.Context, name string) (string, error) {
	p, err := s.Get(ctx, name)
	if err != nil {
		return "", err
	}
	return p.WorktreePath, nil
}

func (s *CompositionService) List(ctx context.Context) ([]Projection, error) {
	store, err := s.storage(ctx)
	if err != nil {
		return nil, err
	}
	entries, err := os.ReadDir(store)
	if errors.Is(err, os.ErrNotExist) {
		return []Projection{}, nil
	}
	if err != nil {
		return nil, err
	}
	var result []Projection
	for _, entry := range entries {
		if !entry.IsDir() || !namePattern.MatchString(entry.Name()) {
			continue
		}
		// Show reservations and incomplete creation intents for recovery.
		record, err := s.readRecord(ctx, entry.Name())
		if errors.Is(err, os.ErrNotExist) {
			result = append(result, Projection{Name: entry.Name()})
			continue
		}
		if err != nil {
			return nil, err
		}
		if record.Creating {
			result = append(result, Projection{Name: entry.Name(), WorktreePath: record.Workspace})
			continue
		}
		p, err := s.Get(ctx, entry.Name())
		if err != nil {
			return nil, err
		}
		result = append(result, p)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Name < result[j].Name })
	return result, nil
}

// Delete removes only the workspace whose embedded ownership marker matches the
// registered projection. As with legacy projection delete, dirty work is lost.
func (s *CompositionService) Delete(ctx context.Context, name string) error {
	release, err := s.acquireCompositionLock(ctx, name)
	if err != nil {
		return err
	}
	defer release()
	record, err := s.readRecord(ctx, name)
	if errors.Is(err, os.ErrNotExist) {
		return s.removeEmptyReservation(ctx, name)
	}
	if err != nil {
		return err
	}
	if record.Creating {
		_, statErr := os.Lstat(record.Workspace)
		if errors.Is(statErr, os.ErrNotExist) {
			return s.removeRecordDirectory(ctx, name)
		}
		if statErr != nil {
			return fmt.Errorf("inspect incomplete workspace %q: %w", record.Workspace, statErr)
		}
	}
	if err := verifyComposition(record); err != nil {
		if record.Creating {
			return fmt.Errorf("refuse to delete unverified incomplete workspace %q: %w; inspect and remove or move it yourself, then retry", record.Workspace, err)
		}
		return fmt.Errorf("refuse to delete composition %q: %w", name, err)
	}
	if err := os.RemoveAll(record.Workspace); err != nil {
		return fmt.Errorf("remove composition workspace: %w", err)
	}
	store, err := s.storage(ctx)
	if err != nil {
		return err
	}
	if err := os.RemoveAll(filepath.Join(store, name)); err != nil {
		return fmt.Errorf("remove composition record: %w", err)
	}
	return nil
}

// removeEmptyReservation removes only layerctl's lock and unfinished atomic
// record writes. Unknown entries, including a workspace, are never removed.
func (s *CompositionService) removeEmptyReservation(ctx context.Context, name string) error {
	dir, err := s.recordDir(ctx, name)
	if err != nil {
		return err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("invalid composition reservation directory")
	}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		if entry.Name() == "lock" {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if !strings.HasPrefix(entry.Name(), ".record-") || !info.Mode().IsRegular() {
			return fmt.Errorf("incomplete reservation %q contains unknown entry %q; inspect and remove it yourself", dir, entry.Name())
		}
	}
	for _, entry := range entries {
		if err := os.Remove(filepath.Join(dir, entry.Name())); err != nil {
			return err
		}
	}
	return os.Remove(dir)
}

func (s *CompositionService) removeRecordDirectory(ctx context.Context, name string) error {
	dir, err := s.recordDir(ctx, name)
	if err != nil {
		return err
	}
	return os.RemoveAll(dir)
}

package projection

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// An exclusive record-directory lock serializes mutations from separate CLI
// processes. A crash can leave it behind; unlock is an explicit operator action
// because the tool cannot safely infer that an unknown owner is dead.
func (s *CompositionService) acquireCompositionLock(ctx context.Context, rawName string) (func(), error) {
	name, err := parseName(rawName)
	if err != nil {
		return nil, err
	}
	dir, err := s.recordDir(ctx, name)
	if err != nil {
		return nil, err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return nil, fmt.Errorf("inspect composition reservation: %w", err)
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return nil, errors.New("composition reservation is not a directory")
	}
	path := filepath.Join(dir, "lock")
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if errors.Is(err, os.ErrExist) {
		return nil, fmt.Errorf("composition %q is locked; after confirming no layerctl process is using it, run layerctl projection unlock %s", name, name)
	}
	if err != nil {
		return nil, fmt.Errorf("lock composition %q: %w", name, err)
	}
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		_ = file.Close()
		_ = os.Remove(path)
		return nil, err
	}
	token := hex.EncodeToString(bytes[:])
	if _, err := fmt.Fprintf(file, "%s pid=%d\n", token, os.Getpid()); err != nil {
		_ = file.Close()
		_ = os.Remove(path)
		return nil, err
	}
	if err := file.Close(); err != nil {
		_ = os.Remove(path)
		return nil, err
	}
	return func() {
		data, err := os.ReadFile(path)
		if err == nil && string(data) == fmt.Sprintf("%s pid=%d\n", token, os.Getpid()) {
			_ = os.Remove(path)
		}
	}, nil
}

// Unlock removes a stale operation lock only when explicitly requested. The
// caller must first confirm no process still owns it; removing a live lock can
// permit concurrent mutations. Ownership of the registered workspace is still
// verified before removing the file.
func (s *CompositionService) Unlock(ctx context.Context, rawName string) error {
	name, err := parseName(rawName)
	if err != nil {
		return err
	}
	record, err := s.readRecord(ctx, name)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if err == nil && !record.Creating {
		if err := verifyComposition(record); err != nil {
			return fmt.Errorf("refuse to unlock composition %q: %w", name, err)
		}
	}
	dir, err := s.recordDir(ctx, name)
	if err != nil {
		return err
	}
	info, err := os.Lstat(dir)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("composition reservation is not a directory")
	}
	if err := os.Remove(filepath.Join(dir, "lock")); err != nil {
		return fmt.Errorf("remove composition lock: %w", err)
	}
	return nil
}

// Modified from abg-OAI/codex: operation fingerprint for resumable advances.
package upstream

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"hash"
	"os"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/projection"
)

// unitFingerprint binds an in-flight advance to the message and ordered data
// it started with. Paths of source files are not part of the operation result.
func unitFingerprint(unit definition.Unit) (string, error) {
	h := sha256.New()
	write := func(data []byte) { writeFingerprintPart(h, data) }
	message := unit.Message
	if message == nil {
		var err error
		message, err = os.ReadFile(unit.MessagePath)
		if err != nil {
			return "", fmt.Errorf("read layer message: %w", err)
		}
	}
	write(message)
	for _, op := range unit.Operations {
		if op.Kind == "script" {
			assets, err := projection.FingerprintScriptAssets(unit.Directory)
			if err != nil {
				return "", fmt.Errorf("fingerprint script assets: %w", err)
			}
			write([]byte("script-assets"))
			write([]byte(assets))
			break
		}
	}
	if len(unit.CoAuthors) > 0 {
		write([]byte("co-authors"))
		for _, author := range unit.CoAuthors {
			write([]byte(author))
		}
		write(nil)
	}
	overlay := func(entries []definition.OverlayEntry) {
		for _, entry := range entries {
			write([]byte(entry.Path))
			write([]byte(entry.Mode))
			write(entry.Data)
		}
		write(nil)
	}
	patch := func(path string) error {
		data, err := os.ReadFile(path)
		if err != nil {
			return fmt.Errorf("read operation patch: %w", err)
		}
		write(data)
		return nil
	}
	if unit.Message == nil {
		write([]byte("legacy"))
		if unit.PatchPath != "" {
			if err := patch(unit.PatchPath); err != nil {
				return "", err
			}
		} else {
			write(nil)
		}
		overlay(unit.Overlay)
	} else {
		write([]byte("manifest"))
		for _, op := range unit.Operations {
			write([]byte(op.Kind))
			switch op.Kind {
			case "patch", "script":
				for _, arg := range op.Args {
					write([]byte(arg))
				}
				write(nil)
				if err := patch(op.Path); err != nil {
					return "", err
				}
			case "overlay":
				overlay(op.Overlay)
			default:
				return "", fmt.Errorf("unsupported operation %q", op.Kind)
			}
		}
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func writeFingerprintPart(h hash.Hash, data []byte) {
	var size [8]byte
	binary.BigEndian.PutUint64(size[:], uint64(len(data)))
	_, _ = h.Write(size[:])
	_, _ = h.Write(data)
}

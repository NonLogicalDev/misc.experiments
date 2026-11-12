// Modified from abg-OAI/codex: module import path changed for this extraction.
package operations

import (
	"bytes"
	"context"
	"fmt"
	"os"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
)

// OverlayCollisionError requires an operator to reconcile newly inherited
// paths, even when Git accepts identical additions without conflict markers.
// No commit is created. Cause retains application failures when the operator
// must reconstruct the complete desired layer rather than resolve markers.
type OverlayCollisionError struct {
	Paths []string
	Cause error
}

func (e *OverlayCollisionError) Error() string {
	if e.Cause != nil {
		return fmt.Sprintf("overlay paths collide with the predecessor: %q; reconcile the complete layer, then refresh: %v", e.Paths, e.Cause)
	}
	return fmt.Sprintf("overlay paths now exist in the predecessor: %q; resolve and refresh the layer", e.Paths)
}

func (e *OverlayCollisionError) Unwrap() error { return e.Cause }

// applicationPatch uses Git to encode overlay blobs as additions after the
// stored patch. No patch parser or filesystem overwrite semantics are needed.
func applicationPatch(ctx context.Context, git *gitrepo.Repository, patchPath string, entries []definition.OverlayEntry) ([]byte, error) {
	var patch []byte
	if patchPath != "" {
		var err error
		patch, err = os.ReadFile(patchPath)
		if err != nil {
			return nil, err
		}
	}
	if len(entries) == 0 {
		return patch, nil
	}
	// Git reports touched paths without interpreting patch syntax here.
	touched := make(map[string]bool)
	if len(patch) != 0 {
		stats, err := git.Invoke(ctx, git.Root, gitrepo.Invocation{
			Arguments: []string{"apply", "--numstat", "-z", "-"}, Stdin: patch,
		})
		if err != nil {
			return nil, fmt.Errorf("inspect patch paths: %w", err)
		}
		for record := range bytes.SplitSeq(stats, []byte{0}) {
			if len(record) == 0 {
				continue
			}
			fields := bytes.SplitN(record, []byte{'\t'}, 3)
			if len(fields) != 3 || len(fields[2]) == 0 {
				return nil, fmt.Errorf("unsupported patch path record %q", record)
			}
			touched[string(fields[2])] = true
		}
	}
	var additions bytes.Buffer
	for _, entry := range entries {
		if err := entry.Validate(); err != nil {
			return nil, err
		}
		if touched[entry.Path] {
			return nil, fmt.Errorf("overlay path %q overlaps the patch or another addition", entry.Path)
		}
		touched[entry.Path] = true
		object, err := git.Invoke(ctx, git.Root, gitrepo.Invocation{
			Arguments: []string{"hash-object", "-w", "--stdin"}, Stdin: entry.Data,
		})
		if err != nil {
			return nil, err
		}
		fmt.Fprintf(&additions, "%s %s\t%s%c", entry.Mode, bytes.TrimSpace(object), entry.Path, 0)
	}
	empty, err := EditTree(ctx, git, "", nil)
	if err != nil {
		return nil, err
	}
	overlay, err := EditTree(ctx, git, "", additions.Bytes())
	if err != nil {
		return nil, err
	}
	delta, err := DiffTrees(ctx, git, empty, overlay)
	if err != nil {
		return nil, err
	}
	return append(append(patch, '\n'), delta...), nil
}

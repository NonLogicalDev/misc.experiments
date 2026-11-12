// Modified from abg-OAI/codex: layer application extracted into operations.
package operations

import (
	"context"
	"strings"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/gitrepo"
)

// ApplyPatchOverlay applies one patch and its optional additive overlay. The
// legacy format combines both into a single three-way application, so clean
// overlay additions remain staged when the patch has conflicts.
func ApplyPatchOverlay(ctx context.Context, git *gitrepo.Repository, worktree, patchPath string, overlay []definition.OverlayEntry) error {
	patch, err := applicationPatch(ctx, git, patchPath, overlay)
	if err != nil {
		return err
	}
	predecessor, err := git.Output(ctx, worktree, "write-tree")
	if err != nil {
		return err
	}
	entries, err := TreeEntries(ctx, git, predecessor)
	if err != nil {
		return err
	}
	var collisions []string
	for _, entry := range overlay {
		for path := range entries {
			if path == entry.Path || strings.HasPrefix(path, entry.Path+"/") || strings.HasPrefix(entry.Path, path+"/") {
				collisions = append(collisions, entry.Path)
				break
			}
		}
	}
	if len(patch) != 0 {
		_, err = git.Invoke(ctx, worktree, gitrepo.Invocation{
			Arguments: []string{"-c", "rerere.enabled=false", "apply", "--3way", "--index", "--whitespace=nowarn", "-"},
			Stdin:     patch,
		})
		if err != nil {
			if len(collisions) != 0 {
				return &OverlayCollisionError{Paths: collisions, Cause: err}
			}
			return err
		}
	}
	var inherited []string
	for _, entry := range overlay {
		if _, exists := entries[entry.Path]; exists {
			inherited = append(inherited, entry.Path)
		}
	}
	if len(inherited) != 0 {
		return &OverlayCollisionError{Paths: inherited}
	}
	return nil
}

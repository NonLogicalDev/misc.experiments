// Package scriptop executes explicitly configured layer scripts. Scripts are
// trusted programs: they can change files, run commands and access networks
// outside the workspace. layerctl cannot roll back those external side effects.
package scriptop

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/NonLogicalDev/misc.experiments/utils/layerctl/internal/definition"
)

// Run executes the script directly with operation args; operationIndex is
// zero-based, while LAYERCTL_OPERATION_INDEX is one-based. The script runs in
// worktree with the caller's environment and five LAYERCTL_* context values.
// On success Git stages workspace changes. Failed scripts are not staged here.
func Run(ctx context.Context, worktree, definitionRoot, layerID, layerDirectory string, operationIndex int, op definition.Operation) error {
	if op.Kind != "script" || operationIndex < 0 {
		return fmt.Errorf("invalid script operation")
	}
	if err := validateScript(layerDirectory, op.Path); err != nil {
		return err
	}
	env := append(os.Environ(),
		"LAYERCTL_WORKTREE_DIR="+worktree,
		"LAYERCTL_DEFINITION_DIR="+definitionRoot,
		"LAYERCTL_LAYER_DIR="+layerDirectory,
		"LAYERCTL_LAYER_ID="+layerID,
		"LAYERCTL_OPERATION_INDEX="+strconv.Itoa(operationIndex+1),
	)
	command := exec.CommandContext(ctx, op.Path, op.Args...)
	command.Dir = worktree
	command.Env = env
	// Projection commands reserve stdout for their requested result.
	command.Stdout = os.Stderr
	command.Stderr = os.Stderr
	if err := command.Run(); err != nil {
		return fmt.Errorf("script operation failed: %w", err)
	}
	stage := exec.CommandContext(ctx, "git", "add", "-A", "--", ".")
	stage.Dir = worktree
	stage.Env = env
	stage.Stderr = os.Stderr
	if err := stage.Run(); err != nil {
		return fmt.Errorf("stage script changes: %w", err)
	}
	return nil
}

// Check every component again immediately before launching. Paths cannot
// escape the declared layer or traverse a symbolic link.
func validateScript(layerDirectory, script string) error {
	base, err := filepath.Abs(layerDirectory)
	if err != nil {
		return err
	}
	path, err := filepath.Abs(script)
	if err != nil {
		return err
	}
	rel, err := filepath.Rel(base, path)
	if err != nil || !filepath.IsLocal(rel) || rel == "." {
		return fmt.Errorf("script must be inside the layer directory")
	}
	current := base
	parts := strings.Split(rel, string(filepath.Separator))
	for i, part := range parts {
		current = filepath.Join(current, part)
		info, err := os.Lstat(current)
		if err != nil {
			return fmt.Errorf("inspect script: %w", err)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("script path contains a symlink")
		}
		if i < len(parts)-1 && !info.IsDir() {
			return fmt.Errorf("script path contains a non-directory")
		}
		if i == len(parts)-1 && (!info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0) {
			return fmt.Errorf("script must be a regular executable file")
		}
	}
	return nil
}
